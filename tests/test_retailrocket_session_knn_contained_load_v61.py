"""Artificial adjacent-pair telemetry only; no saved measurements or APIs."""
from copy import deepcopy
import json
import unittest

from scripts.retailrocket_session_knn_contained_load_v61 import (
    summarize_selected, flatten_metrics, DISK_KEYS, METRICS, DELTA_UNITS)


def records_fixture():
    records = []
    for index, start in enumerate((0., 1., 3., 6., 10.)):
        worker = dict(pid=10, create_time=2., name='synthetic-worker', status='observed',
            cpu_user_seconds=(0., .2, 1.2, 2.1, 4.1)[index], cpu_system_seconds=0.,
            rss_bytes=100 + index * 10)
        ollama = dict(pid=20, create_time=3., name='ollama-synthetic', status='observed',
            cpu_user_seconds=(0., .1, .3, .6, 1.)[index], cpu_system_seconds=0., rss_bytes=50)
        records.append(dict(sequence=index, monotonic_seconds=start, collector_seconds=.1,
            system_cpu_percent=(None, 10., 40., 70., 20.)[index], worker=worker, ollama=[ollama],
            ollama_scan_status='ok', disk_io_status='ok',
            disk_io={key: index * (position + 1) * 10 for position, key in enumerate(DISK_KEYS)},
            memory=dict(available_bytes=1000 + index * 100)))
    return records


def coverage_fixture(selected=(0, 1), *, extras=()):
    chosen = set(selected)
    return dict(phase_duration_ns=20_000_000_000,
        capture_contained_interior_duration_ns=10_000_000_000,
        capture_contained_interior_share=.5, capture_hull_contained_count=len(chosen),
        intervals=[dict(left_sequence=index, right_sequence=index+1, capture_hull_contained=index in chosen)
                   for index in sorted(chosen | set(extras))],
        capture_hull_only_intervals=[dict(left_sequence=0, right_sequence=1)])


class ContainedLoadTests(unittest.TestCase):
    def test_unequal_nominal_weights_do_not_use_interior_or_phase_duration(self):
        result = summarize_selected(records_fixture(), coverage_fixture())
        self.assertEqual(result['selection']['selected_duration_seconds'], 3.)
        self.assertEqual(result['system_cpu']['percent'], dict(min=10., mean=30., max=40.))
        self.assertAlmostEqual(result['worker_cpu']['core_percent']['mean'], 40.)
        self.assertAlmostEqual(result['worker_cpu']['cpu_delta_seconds_sum'], 1.2)
        self.assertEqual(result['worker_cpu']['valid_duration_seconds'], 3.)

    def test_noncontiguous_pairs_never_bridge_excluded_gap(self):
        records = records_fixture()
        records[2]['disk_io']['read_bytes'] = 30000
        # The unselected 1->2 and 2->3 intervals must not enter the disk total.
        result = summarize_selected(records, coverage_fixture((0, 3), extras=(1, 2)))
        self.assertEqual(result['selection']['selected_pairs'], [[0, 1], [3, 4]])
        self.assertEqual(result['selection']['selected_duration_seconds'], 5.)
        self.assertEqual(result['disk']['counter_delta']['read_bytes'], 20)
        self.assertEqual(result['disk']['valid_intervals'], 2)
        self.assertEqual(result['system_cpu']['percent']['mean'], 18.)

    def test_shared_endpoint_is_counted_once_in_point_summaries(self):
        result = summarize_selected(records_fixture(), coverage_fixture())
        self.assertEqual(result['selection']['endpoint_sequences'], [0, 1, 2])
        point = result['points']['available_memory_bytes']
        self.assertEqual(point['total_count'], 3)
        self.assertEqual(point['stats'], dict(min=1000, mean=1100, max=1200))
        self.assertEqual(result['points']['worker_rss_bytes']['stats']['mean'], 110)

    def test_boundary_and_hull_only_pairs_are_not_selected(self):
        result = summarize_selected(records_fixture(), coverage_fixture((1,), extras=(0, 2, 3)))
        self.assertEqual(result['selection']['selected_pairs'], [[1, 2]])
        self.assertEqual(result['selection']['excluded_nominal_intervals'], 3)
        self.assertEqual(result['selection']['excluded_hull_only_intervals'], 1)
        self.assertEqual(result['system_cpu']['percent']['mean'], 40.)

    def test_worker_reset_rejects_only_original_affected_pair(self):
        records = records_fixture()
        records[2]['worker']['cpu_user_seconds'] = .1
        result = summarize_selected(records, coverage_fixture())['worker_cpu']
        self.assertEqual(result['valid_intervals'], 1)
        self.assertEqual(result['invalid_intervals'], 1)
        self.assertEqual(result['invalid_duration_seconds'], 2.)
        self.assertEqual(result['unavailable_reasons'], dict(counter_reset=1))
        self.assertEqual(result['core_percent']['mean'], 20.)

    def test_identity_change_missing_status_and_invalid_counter_are_unavailable(self):
        for mutation, reason in (('identity', 'identity_set_changed'), ('status', 'process_unavailable'),
                                 ('counter', 'counter_unavailable')):
            records = records_fixture()
            if mutation == 'identity': records[1]['worker']['create_time'] = 4.
            elif mutation == 'status': records[1]['worker']['status'] = 'AccessDenied'
            else: records[1]['worker']['cpu_user_seconds'] = None
            value = summarize_selected(records, coverage_fixture((0,)))['worker_cpu']
            with self.subTest(mutation=mutation):
                self.assertEqual(value['unavailable_reasons'], {reason: 1})
                self.assertIsNone(value['core_percent'])
                self.assertIsNone(value['cpu_delta_seconds_sum'])

    def test_partial_ollama_identity_set_is_not_common_subset_cpu(self):
        records = records_fixture()
        records[1]['ollama'].append(dict(records[1]['ollama'][0], pid=21))
        value = summarize_selected(records, coverage_fixture((0,)))['ollama_cpu']
        self.assertEqual(value['valid_intervals'], 0)
        self.assertEqual(value['unavailable_reasons'], dict(identity_set_changed=1))
        self.assertIsNone(value['core_percent'])

    def test_empty_or_partial_scan_ollama_is_missing_not_zero(self):
        for mutation, reason in (('empty', 'not_observed'), ('scan', 'scan_unavailable')):
            records = records_fixture()
            for row in records:
                if mutation == 'empty': row['ollama'] = []
                else: row['ollama_scan_status'] = 'partially_unavailable_process_names'
            summary = summarize_selected(records, coverage_fixture())
            with self.subTest(mutation=mutation):
                self.assertEqual(summary['ollama_cpu']['unavailable_reasons'], {reason: 2})
                self.assertIsNone(flatten_metrics(summary)['ollama_cpu_mean_core_percent'])
                self.assertIsNone(summary['points']['ollama_rss_bytes']['stats'])

    def test_disk_reset_missing_or_changed_schema_keeps_invalid_duration_out(self):
        for mutation, reason in (('reset', 'counter_reset'), ('missing', 'counter_unavailable'),
                                 ('schema', 'counter_schema_changed')):
            records = records_fixture()
            if mutation == 'reset': records[2]['disk_io']['write_count'] = 0
            elif mutation == 'missing': records[2]['disk_io'] = None
            else: records[2]['disk_io'].pop('read_time')
            value = summarize_selected(records, coverage_fixture())['disk']
            with self.subTest(mutation=mutation):
                self.assertEqual(value['valid_intervals'], 1)
                self.assertEqual(value['valid_duration_seconds'], 1.)
                self.assertEqual(value['unavailable_reasons'], {reason: 1})
                self.assertEqual(value['counter_delta']['read_bytes'], 10)

    def test_unavailable_system_cpu_reweights_valid_intervals_only(self):
        records = records_fixture()
        records[2]['system_cpu_percent'] = None
        value = summarize_selected(records, coverage_fixture())['system_cpu']
        self.assertEqual(value['percent']['mean'], 10.)
        self.assertEqual(value['valid_duration_seconds'], 1.)
        self.assertEqual(value['invalid_intervals'], 1)

    def test_missing_point_stays_missing_without_duplicate_recovery(self):
        records = records_fixture()
        records[1]['memory']['available_bytes'] = None
        records[1]['worker']['rss_bytes'] = None
        result = summarize_selected(records, coverage_fixture())
        for name in ('available_memory_bytes', 'worker_rss_bytes'):
            self.assertEqual(result['points'][name]['valid_count'], 2)
            self.assertEqual(result['points'][name]['missing_count'], 1)

    def test_no_selected_intervals_retains_null_resource_summaries(self):
        result = summarize_selected(records_fixture(), coverage_fixture((), extras=(0, 1)))
        self.assertEqual(result['selection']['selected_duration_seconds'], 0.)
        self.assertEqual(result['selection']['endpoint_sequences'], [])
        self.assertIsNone(result['system_cpu']['percent'])
        self.assertIsNone(result['worker_cpu']['cpu_delta_seconds_sum'])
        self.assertIsNone(result['disk']['counter_delta'])
        for point in result['points'].values():
            self.assertEqual(point['total_count'], 0)
            self.assertIsNone(point['stats'])

    def test_zero_cpu_and_disk_deltas_remain_valid_zero(self):
        records = records_fixture()
        records[1]['worker']['cpu_user_seconds'] = 0.
        records[1]['disk_io'] = deepcopy(records[0]['disk_io'])
        result = summarize_selected(records, coverage_fixture((0,)))
        self.assertEqual(result['worker_cpu']['cpu_delta_seconds_sum'], 0.)
        self.assertEqual(result['worker_cpu']['core_percent']['mean'], 0.)
        self.assertEqual(result['disk']['counter_delta'], dict.fromkeys(DISK_KEYS, 0))

    def test_system_counter_reset_is_not_hidden_by_increasing_user_cpu(self):
        records = records_fixture()
        records[0]['worker']['cpu_system_seconds'] = 1.
        records[1]['worker']['cpu_user_seconds'] = 2.
        result = summarize_selected(records, coverage_fixture((0,)))['worker_cpu']
        self.assertIsNone(result['core_percent'])
        self.assertEqual(result['unavailable_reasons'], dict(counter_reset=1))
        records[0]['worker']['cpu_system_seconds'] = 0.
        result = summarize_selected(records, coverage_fixture((0,)))['worker_cpu']
        self.assertEqual(result['core_percent']['mean'], 200.)
        self.assertEqual(result['invalid_duration_seconds'], 0.)

    def test_flat_metrics_units_and_raw_identity_privacy(self):
        result = summarize_selected(records_fixture(), coverage_fixture())
        flat = flatten_metrics(result)
        self.assertEqual(tuple(flat), METRICS)
        self.assertEqual(len(flat), 18)
        self.assertEqual(DELTA_UNITS['system_cpu_mean_percent'], 'percentage_points_all_logical_cpus')
        encoded = json.dumps(result)
        for field in ('pid', 'create_time', 'synthetic-worker', 'ollama-synthetic'):
            self.assertNotIn(field, encoded)

    def test_inputs_are_unchanged_and_bad_pair_identities_fail(self):
        records, coverage = records_fixture(), coverage_fixture()
        before = deepcopy((records, coverage))
        summarize_selected(records, coverage)
        self.assertEqual((records, coverage), before)
        for mutation in ('duplicate', 'nonadjacent', 'boolean', 'count', 'sequence', 'clock', 'share'):
            records, coverage = records_fixture(), coverage_fixture()
            if mutation == 'duplicate': coverage['intervals'].append(deepcopy(coverage['intervals'][-1]))
            elif mutation == 'nonadjacent': coverage['intervals'][0]['right_sequence'] = 2
            elif mutation == 'boolean': coverage['intervals'][0]['capture_hull_contained'] = 1
            elif mutation == 'count': coverage['capture_hull_contained_count'] += 1
            elif mutation == 'sequence': records[1]['sequence'] = 0
            elif mutation == 'clock': records[1]['monotonic_seconds'] = float('nan')
            else: coverage['capture_contained_interior_share'] = .7
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                summarize_selected(records, coverage)


if __name__ == '__main__':
    unittest.main()
