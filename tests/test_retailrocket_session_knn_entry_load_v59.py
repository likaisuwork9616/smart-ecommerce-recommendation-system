"""Synthetic summaries only: never load historical measurements."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_entry_load_v59 import (
    analyze_load_reports, flatten_load, SCHEDULE, METRICS, DELTA_UNITS)


def load_fixture(cpu=20, max_gap=.25):
    process = dict(status='observed', observed_processes=1,
        cpu_core_percent=dict(min=80, mean=100, max=120), rss_bytes=dict(min=100, mean=110, max=120),
        valid_cpu_intervals=4, valid_cpu_duration_seconds=1,
        unavailable_observations=0, discontinuous_cpu_intervals=0, partial_cpu_intervals=0)
    return dict(duration_seconds=1, samples=5, nominal_interval_seconds=.2,
        system_cpu_percent=dict(min=cpu, mean=cpu, max=cpu),
        available_memory_bytes=dict(min=1000, mean=2000, max=3000),
        collector_seconds=dict(min=.01, mean=.02, max=.03), total_collector_seconds=.1,
        worker=deepcopy(process), ollama=deepcopy(process),
        disk_io_delta=dict(read_bytes=10, write_bytes=20, read_count=1, write_count=2, read_time=0, write_time=0),
        disk_valid_intervals=4, disk_unavailable_or_reset_intervals=0,
        disk_status_counts=dict(ok=5), ollama_scan_status_counts=dict(ok=5),
        coverage=dict(intervals=4, max_gap_seconds=max_gap, missing_periodic_intervals=0))


def reports_fixture():
    reports = {}
    for window in ('V47', 'V48'):
        runs = {}
        for item in SCHEDULE:
            label, arm = item['label'], item['mode']
            pair = int(label.split('_')[1]) if label.startswith('pair_') else 1000
            entry = pair + (2 if arm == 'C' else 0) + (10 if window == 'V48' else 0)
            runs[label] = dict(mode=arm, accounting=dict(costs=dict(entry_seconds=entry)),
                load=load_fixture(cpu=20+(5 if arm == 'C' else 0)))
        reports[window] = dict(schedule=deepcopy(SCHEDULE), runs=runs, publisher_load=load_fixture(cpu=90))
    return reports


class EntryLoadTests(unittest.TestCase):
    def test_every_pair_absolute_values_delta_and_execution_order(self):
        result = analyze_load_reports(reports_fixture())
        for window in result['windows'].values():
            self.assertEqual([row['order'] for row in window['pairs']], ['CR', 'RC'] * 3)
            self.assertEqual([row['run_position'] for row in window['formal_entries']], list(range(3, 15)))
            self.assertEqual([row['pair'] for row in window['pairs']], list(range(1, 7)))
            for pair in window['pairs']:
                self.assertEqual(set(pair['R']), set(METRICS))
                for key in METRICS:
                    self.assertEqual(pair['delta_C_minus_R'][key], pair['C'][key]-pair['R'][key])
                self.assertEqual(pair['delta_C_minus_R']['system_cpu_mean_percent'], 5)
            self.assertEqual(window['entry_direction_counts'], dict(candidate_slower=6, candidate_faster=0, equal=0))

    def test_warm_and_publisher_are_preserved_but_excluded(self):
        result = analyze_load_reports(reports_fixture())['windows']['V47']
        self.assertEqual(result['formal_by_arm']['R']['entry_seconds'],
                         dict(count=6, valid=6, missing=0, min=1, median=3.5, max=6))
        self.assertEqual([row['label'] for row in result['warm_entries']], ['warm_R', 'warm_C'])
        self.assertEqual(result['warm_entries'][0]['metrics']['entry_seconds'], 1000)
        self.assertIsNone(result['publisher']['metrics']['entry_seconds'])
        self.assertEqual(result['publisher']['metrics']['system_cpu_mean_percent'], 90)

    def test_cross_window_is_difference_of_arm_medians(self):
        result = analyze_load_reports(reports_fixture())
        self.assertEqual(result['between_window_arm_medians']['R']['entry_seconds'],
            dict(V47=3.5, V48=13.5, median_difference_V48_minus_V47=10))
        self.assertEqual(result['windows']['V47']['pair_delta_summary']['entry_seconds']['median'], 2)
        self.assertEqual(DELTA_UNITS['system_cpu_mean_percent'], 'percentage_points_all_logical_cpus')

    def test_input_and_returned_nested_values_are_not_aliased(self):
        source = reports_fixture(); before = deepcopy(source)
        result = analyze_load_reports(source)
        self.assertEqual(source, before)
        result['windows']['V47']['pairs'][0]['R']['entry_seconds'] = 999
        result['windows']['V47']['formal_entries'][0]['load_quality']['disk_status_counts']['ok'] = 0
        self.assertEqual(source, before)

    def test_unavailable_process_and_disk_remain_null_with_valid_counts(self):
        reports = reports_fixture()
        for label in [x['label'] for x in SCHEDULE if x['mode'] == 'C']:
            load = reports['V47']['runs'][label]['load']
            load['ollama'].update(status='not_observed_or_unavailable', observed_processes=0,
                cpu_core_percent=None, rss_bytes=None, valid_cpu_intervals=0, valid_cpu_duration_seconds=0)
            load.update(disk_io_delta=None, disk_valid_intervals=0, disk_unavailable_or_reset_intervals=4,
                        disk_status_counts=dict(unsupported=5))
        result = analyze_load_reports(reports)['windows']['V47']
        for name in ('disk_read_bytes', 'ollama_cpu_mean_core_percent'):
            self.assertIsNone(result['pairs'][0]['delta_C_minus_R'][name])
            self.assertEqual(result['formal_by_arm']['C'][name],
                dict(count=6, valid=0, missing=6, min=None, median=None, max=None))

    def test_partial_missing_deltas_do_not_become_zero(self):
        reports = reports_fixture()
        load = reports['V47']['runs']['pair_2_C']['load']
        load.update(disk_io_delta=None, disk_valid_intervals=0, disk_unavailable_or_reset_intervals=4)
        result = analyze_load_reports(reports)['windows']['V47']['pair_delta_summary']['disk_read_bytes']
        self.assertEqual(result, dict(count=6, valid=5, missing=1, min=0, median=0, max=0))

    def test_exact_entry_signs_include_zero_without_significance_threshold(self):
        reports = reports_fixture()
        reports['V47']['runs']['pair_1_C']['accounting']['costs']['entry_seconds'] = 1
        reports['V47']['runs']['pair_2_C']['accounting']['costs']['entry_seconds'] = 1.9999999
        counts = analyze_load_reports(reports)['windows']['V47']['entry_direction_counts']
        self.assertEqual(counts, dict(candidate_slower=4, candidate_faster=1, equal=1))

    def test_wrong_window_scope_schedule_missing_extra_and_arm_are_rejected(self):
        for case in ('missing_window', 'extra_window', 'order', 'missing_run', 'extra_run', 'arm'):
            reports = reports_fixture()
            if case == 'missing_window': reports.pop('V48')
            elif case == 'extra_window': reports['V49'] = reports['V48']
            elif case == 'order': reports['V47']['schedule'][2:4] = reports['V47']['schedule'][2:4][::-1]
            elif case == 'missing_run': reports['V47']['runs'].pop('pair_6_C')
            elif case == 'extra_run': reports['V47']['runs']['other'] = reports['V47']['runs']['warm_R']
            else: reports['V47']['runs']['pair_1_R']['mode'] = 'C'
            with self.subTest(case=case), self.assertRaises(ValueError): analyze_load_reports(reports)

    def test_nonfinite_boolean_and_invalid_entry_values_are_rejected(self):
        for value in (True, None, 0, -1, float('nan'), float('inf'), 10**400):
            reports = reports_fixture()
            reports['V47']['runs']['pair_1_C']['accounting']['costs']['entry_seconds'] = value
            with self.subTest(value=str(value)), self.assertRaises(ValueError): analyze_load_reports(reports)

    def test_coverage_disk_and_acquisition_accounting_fail_closed(self):
        for case in ('intervals', 'disk', 'nominal', 'gap', 'collector', 'status', 'cpu_coverage'):
            load = load_fixture()
            if case == 'intervals': load['coverage']['intervals'] = 3
            elif case == 'disk': load['disk_valid_intervals'] = 3
            elif case == 'nominal': load['nominal_interval_seconds'] = .1
            elif case == 'gap': load['coverage']['max_gap_seconds'] = 2
            elif case == 'collector': load['total_collector_seconds'] = 5
            elif case == 'status': load['disk_status_counts']['ok'] = 4
            else: load['worker']['valid_cpu_intervals'] = 5
            with self.subTest(case=case), self.assertRaises(ValueError): flatten_load(load, 1)

    def test_invalid_counter_or_statistic_values_are_rejected(self):
        for case in ('disk_bool', 'count_float', 'system_101', 'mean_order', 'null_system', 'negative_missing'):
            load = load_fixture()
            if case == 'disk_bool': load['disk_io_delta']['read_bytes'] = True
            elif case == 'count_float': load['samples'] = 5.0
            elif case == 'system_101': load['system_cpu_percent']['max'] = 101
            elif case == 'mean_order': load['worker']['cpu_core_percent']['mean'] = 200
            elif case == 'null_system': load['system_cpu_percent'] = None
            else: load['coverage']['missing_periodic_intervals'] = -1
            with self.subTest(case=case), self.assertRaises(ValueError): flatten_load(load, 1)

    def test_process_cpu_above_100_and_host_disk_zero_time_are_retained(self):
        load = load_fixture()
        load['worker']['cpu_core_percent'] = dict(min=120, mean=130, max=150)
        row = flatten_load(load, 1)
        self.assertEqual(row['metrics']['worker_cpu_mean_core_percent'], 130)
        self.assertEqual(row['metrics']['disk_read_time'], 0)
        self.assertEqual(row['load_quality']['worker']['valid_cpu_intervals'], 4)


if __name__ == '__main__':
    unittest.main()
