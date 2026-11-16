"""A16 literal synthetic records only; no clocks, sleep, SQL or workloads run."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_wall_cpu_decision_v65 import (
    evaluate_capability, evaluate_artificial_overhead, evaluate_window)


EVIDENCE = []
SOURCE = 'a'*64
PHASES = ('sql_positive_overlaps', 'sql_selected_votes_and_accumulation')
METRIC_SOURCE = 'accounting.costs.entry_seconds from entry.json.seconds'


def capability_fixture(*, offset=0, cpu_steps=None, sleep_cpus=None, sleep_walls=None):
    """Three literal 0.5 s busy traces, then ten literal sleep traces.

    Sparse artificial readings are enough for decision arithmetic; they are
    not a sampling algorithm or measured evidence of this computer's clocks.
    """
    steps = cpu_steps if cpu_steps is not None else [[10_000]*10 for _ in range(3)]
    sleep_cpus = [1_000_000]*10 if sleep_cpus is None else sleep_cpus
    sleep_walls = [50_000_000]*10 if sleep_walls is None else sleep_walls
    cpu = offset//10
    rounds = []

    def stamp(wall, value):
        return dict(wall_before_ns=wall, thread_cpu_ns=value, wall_after_ns=wall+1, thread_id=73)

    for number, increments in enumerate(steps, 1):
        start = offset+10_000_000+(number-1)*600_000_000
        stamps = [stamp(start, cpu)]
        for index, increment in enumerate(increments, 1):
            cpu += increment
            stamps.append(stamp(start+500_000_000*index//len(increments), cpu))
        rounds.append(dict(round=number, completed=True, stop_reason='wall_target', stamps=stamps))
        cpu += 1
    sleeps = []
    for trial, (increment, wall) in enumerate(zip(sleep_cpus, sleep_walls), 1):
        start = offset+1_900_000_000+(trial-1)*100_000_000
        before = stamp(start, cpu)
        cpu += increment
        sleeps.append(dict(trial=trial, completed=True, requested_ns=50_000_000,
                           start=before, end=stamp(start+wall, cpu)))
        cpu += 1
    return dict(origin='synthetic_fixture', completed=True, started_wall_ns=offset,
        ended_wall_ns=offset+3_000_000_000, elapsed_wall_ns=3_000_000_000,
        environment=dict(python='synthetic-python', os='synthetic-os', process_id=19,
                         thread_id=73, source_sha256=SOURCE),
        clocks={name: dict(api=api, available=True, implementation='synthetic-'+name,
            monotonic=True, adjustable=False, resolution_seconds='0.000000001')
            for name, api in (('wall', 'time.perf_counter_ns'), ('cpu', 'time.thread_time_ns'))},
        rounds=rounds, sleeps=sleeps)


def overhead_fixture():
    probes = {name: [dict(outer_wall_ns=30, completed=True, clock_reads=dict(wall=2, cpu=1),
        allocation_ns=0 if name == 'empty_stamp' else 2,
        append_ns=0 if name == 'empty_stamp' else 3,
        dispatch_ns=0 if name == 'empty_stamp' else 4) for _ in range(4097)]
        for name in ('empty_stamp', 'full_recording')}
    workloads = []
    for name in ('lcg', 'sleep'):
        labels = [('warm_O', 'O'), ('warm_D', 'D')]
        for number, order in enumerate(('OD', 'DO', 'OD', 'DO', 'OD', 'DO', 'OD', 'DO'), 1):
            labels.extend((f'pair_{number}_{mode}', mode) for mode in order)
        rows = [dict(label=label, mode=mode, wall_ns=1_000_000_000, completed=True,
            namespace=name+':'+label, outer_includes_output=True,
            trace_sha256='b'*64, checksum_sha256=('c' if name == 'lcg' else 'd')*64)
            for label, mode in labels]
        workloads.append(dict(name=name, elapsed_wall_ns=20_000_000_000,
            configuration=dict(queries=48, query_points=7, ranking_points=8, setup_tail_points=5,
                lcg_seed=1, lcg_multiplier=1664525, lcg_increment=1013904223,
                lcg_modulus=4294967296, lcg_iterations=4096, sleep_requested_ns=1_000_000), rows=rows))
    return dict(origin='synthetic_fixture', capability=capability_fixture(), probes=probes, workloads=workloads)


def window_fixture():
    cohort = [dict(subset_ordinal=i, original_ordinal=100+2*i, key_sha256=f'{i+1:064x}') for i in range(48)]
    schedule = [('warm_V39_O', 'V39', 'O', 0), ('warm_V46_D', 'V46', 'D', 0),
                ('warm_V46_O', 'V46', 'O', 0), ('warm_V39_D', 'V39', 'D', 0)]
    for block, decoders, modes in ((1, ('V39', 'V46'), 'OD'), (2, ('V46', 'V39'), 'DO'),
        (3, ('V39', 'V46'), 'OD'), (4, ('V46', 'V39'), 'DO'),
        (5, ('V39', 'V46'), 'OD'), (6, ('V46', 'V39'), 'DO')):
        schedule.extend((f'block_{block}_{decoder}_{mode}', decoder, mode, block)
                        for decoder in decoders for mode in modes)
    entries, calibrations = [], []
    for index, (label, decoder, mode, block) in enumerate(schedule):
        before_start = index*10_000_000_000
        entry_start = before_start+3_000_000_100
        entry_end = entry_start+1_000_000_000
        after_start = entry_end+1
        entries.append(dict(label=label, decoder=decoder, mode=mode, block=block,
            namespace='fresh:'+label, completed=True, thread_id=73, cohort=deepcopy(cohort),
            source_sha256=SOURCE, original_entry_metric=METRIC_SOURCE,
            metrics=dict(instrumentation_entry_ns=1_000_000_000, original_entry_ns=900_000_000,
                run_total_ns=950_000_000, entry_span_ns=980_000_000,
                query_wall_ns=[10_000_000]*48,
                sql_positive_overlaps=[2_000_000]*48,
                sql_selected_votes_and_accumulation=[1_000_000]*48),
            timeline=dict(before_calibration_end_ns=before_start+3_000_000_000,
                sampler_first_ns=before_start+3_000_000_001, instrumentation_start_ns=entry_start,
                instrumentation_end_ns=entry_end, sampler_last_ns=after_start,
                after_calibration_start_ns=after_start),
            event_brackets_ns=[] if mode == 'O' else [1]*725,
            agreement=dict(payload_equal=True, workload_equal=True, ledger_equal=True,
                           source_verified=True, outer_scope_verified=True),
            calibration_before=label+':before', calibration_after=label+':after'))
        for position, offset in (('before', before_start), ('after', after_start)):
            calibrations.append(dict(id=label+':'+position, entry_label=label,
                                     position=position, capability=capability_fixture(offset=offset)))
    return dict(origin='synthetic_fixture', started_wall_ns=0, ended_wall_ns=280_000_000_000,
        elapsed_wall_ns=280_000_000_000, prerequisite_C=overhead_fixture(), cohort=cohort,
        source_sha256=SOURCE, entries=entries, calibrations=calibrations)


def formal(record, decoder, block, mode):
    return next(row for row in record['entries'] if (row['decoder'], row['block'], row['mode']) == (decoder, block, mode))


def instrumentation_value(record, row, value):
    """Move the attached after-calibration when changing its enclosing metric."""
    row['metrics']['instrumentation_entry_ns'] = value
    end = row['timeline']['instrumentation_start_ns']+value
    row['timeline'].update(instrumentation_end_ns=end, sampler_last_ns=end+1,
                           after_calibration_start_ns=end+1)
    index = record['entries'].index(row)
    record['calibrations'][2*index+1]['capability'] = capability_fixture(offset=end+1)


class CapabilityDecisionTests(unittest.TestCase):
    def test_complete_capability_recomputes_all_raw_statistics(self):
        record = capability_fixture()
        result = evaluate_capability(record)
        self.assertEqual(result['status'], 'clock_capability_passed')
        self.assertEqual(result['q_ns'], 10_000)
        self.assertEqual(result['brackets']['count'], 53)
        self.assertEqual((result['brackets']['p99'], result['brackets']['max']), (1, 1))
        self.assertEqual(result['sleep_ratio_p90_exact'], dict(numerator=1, denominator=50))
        for row in result['rounds']:
            self.assertEqual(row['elapsed_wall_ns'], 500_000_000)
            self.assertEqual(row['positive_cpu_increments']['count'], 10)
            self.assertEqual(row['positive_cpu_increments']['p95'], 10_000)
            self.assertEqual(row['zero_cpu_ratio_exact'], dict(numerator=0, denominator=1))
        self.assertFalse(result['live_measurement_executed'])
        self.assertFalse(result['authorized_next_measurement'])
        EVIDENCE.append(dict(case='B_provided_synthetic_records', status=result['status'],
            rounds=3, sleep_trials=10, raw_brackets=53, q_ns=10_000,
            live_measurement_executed=False))

    def test_resolution_ceil_exact_edge_and_above_edge(self):
        for seconds, expected, status in (('0.0001', 100_000, 'clock_capability_passed'),
            ('0.0001000000001', 100_001, 'cpu_resolution_insufficient')):
            record = capability_fixture(); record['clocks']['cpu']['resolution_seconds'] = seconds
            result = evaluate_capability(record)
            self.assertEqual(result['declared_resolution_ceil_ns']['cpu'], expected)
            self.assertEqual(result['q_ns'], expected)
            self.assertEqual(result['status'], status)

    def test_q_uses_each_round_positive_p95_not_minimum_or_gcd(self):
        record = capability_fixture(cpu_steps=[[100_001]*10, [10_000]*10, [10_000]*10])
        result = evaluate_capability(record)
        self.assertEqual(result['q_ns'], 100_001)
        self.assertEqual(result['status'], 'cpu_resolution_insufficient')
        record = capability_fixture(cpu_steps=[[10_000]*19+[900_000], [10_000]*10, [10_000]*10])
        result = evaluate_capability(record)
        self.assertEqual(result['rounds'][0]['positive_cpu_increments']['max'], 900_000)
        self.assertEqual(result['rounds'][0]['positive_cpu_increments']['p95'], 10_000)
        self.assertEqual(result['status'], 'clock_capability_passed')

    def test_zero_increments_preserved_and_positive_minimum_required(self):
        record = capability_fixture(cpu_steps=[[0]+[10_000]*9, [10_000]*10, [10_000]*10])
        result = evaluate_capability(record)
        self.assertEqual(result['status'], 'clock_capability_unconfirmed')
        self.assertEqual(result['rounds'][0]['zero_cpu_ratio_exact'], dict(numerator=1, denominator=10))
        self.assertIn('round_1_insufficient_positive_cpu', result['failure_reasons'])

    def test_round_missing_short_capped_and_deadline_keep_failure_evidence(self):
        for case in ('missing', 'short', 'cap', 'deadline', 'unfinished'):
            record = capability_fixture()
            if case == 'missing': record['rounds'][1] = None
            elif case == 'short':
                for index, stamp in enumerate(record['rounds'][0]['stamps']):
                    stamp['wall_before_ns'] = 10_000_000+40_000_000*index
                    stamp['wall_after_ns'] = stamp['wall_before_ns']+1
            elif case == 'cap': record['rounds'][0].update(completed=False, stop_reason='sample_cap')
            elif case == 'deadline': record.update(ended_wall_ns=30_000_000_001, elapsed_wall_ns=30_000_000_001)
            else: record['completed'] = False
            with self.subTest(case=case):
                result = evaluate_capability(record)
                self.assertEqual(result['status'], 'clock_capability_unconfirmed')
                self.assertEqual(result['records'], record)

    def test_bracket_p99_and_max_are_separate_exact_limits(self):
        for count, bracket, status in ((2, 50_000, 'clock_capability_passed'),
            (2, 50_001, 'clock_capability_unconfirmed'), (1, 100_000, 'clock_capability_passed'),
            (1, 100_001, 'clock_capability_unconfirmed')):
            record = capability_fixture(cpu_steps=[[10_000]*100, [10_000]*10, [10_000]*10])
            for stamp in record['rounds'][0]['stamps'][:count]:
                stamp['wall_after_ns'] = stamp['wall_before_ns']+bracket
            with self.subTest(count=count, bracket=bracket):
                result = evaluate_capability(record)
                self.assertEqual(result['brackets']['count'], 143)
                self.assertEqual(result['status'], status)

    def test_sleep_uses_actual_wall_and_exact_p90_cpu_ratio(self):
        for cpus, walls, status in (([5_000_000]*10, [50_000_000]*10, 'clock_capability_passed'),
            ([5_000_001]*2+[5_000_000]*8, [50_000_000]*10, 'clock_capability_unconfirmed'),
            ([10_000_000]+[1_000_000]*9, [50_000_000]*10, 'clock_capability_passed'),
            ([1_000_000]*10, [39_999_999]+[50_000_000]*9, 'clock_capability_unconfirmed')):
            record = capability_fixture(sleep_cpus=cpus, sleep_walls=walls)
            result = evaluate_capability(record)
            self.assertEqual(result['status'], status)
            self.assertEqual(result['sleeps'][0]['wall_ns'], walls[0])

    def test_metadata_clock_availability_and_api_substitution_fail_closed(self):
        for field, value in (('available', False), ('monotonic', False), ('adjustable', True),
                             ('resolution_seconds', None)):
            record = capability_fixture(); record['clocks']['cpu'][field] = value
            self.assertEqual(evaluate_capability(record)['status'], 'clock_capability_unconfirmed')
        record = capability_fixture(); record['clocks']['cpu']['api'] = 'time.process_time_ns'
        self.assertEqual(evaluate_capability(record)['status'], 'rejected_structure')
        record = capability_fixture(); record['clocks']['cpu']['resolution_seconds'] = '1/0'
        self.assertEqual(evaluate_capability(record)['status'], 'rejected_structure')

    def test_strict_types_thread_backward_and_outer_envelope_are_rejected(self):
        mutations = (
            lambda r: r.update(elapsed_wall_ns=True),
            lambda r: r['clocks']['cpu'].update(monotonic=1),
            lambda r: r['rounds'][0]['stamps'][1].update(thread_cpu_ns=1.0),
            lambda r: r['rounds'][0]['stamps'][1].update(thread_id=74),
            lambda r: r['rounds'][0]['stamps'][2].update(thread_cpu_ns=5_000),
            lambda r: r['rounds'][1]['stamps'][0].update(wall_before_ns=1, wall_after_ns=2),
            lambda r: r.update(ended_wall_ns=0, elapsed_wall_ns=0),
            lambda r: r.update(origin='actual_measurement'),
        )
        for mutation in mutations:
            record = capability_fixture(); mutation(record)
            self.assertEqual(evaluate_capability(record)['status'], 'rejected_structure')


class ArtificialOverheadDecisionTests(unittest.TestCase):
    def test_complete_two_workloads_probe_diagnostics_and_all_pairs(self):
        result = evaluate_artificial_overhead(overhead_fixture())
        self.assertEqual(result['status'], 'artificial_perturbation_passed')
        for name in ('empty_stamp', 'full_recording'):
            self.assertEqual(result['probes'][name]['outer_wall_ns']['count'], 4097)
            self.assertEqual(result['probes'][name]['actual_added_clock_reads'], dict(wall=8194, cpu=4097))
        for name in ('lcg', 'sleep'):
            self.assertEqual(result['workloads'][name]['gate']['valid_pairs'], 8)
            self.assertEqual(len(result['workloads'][name]['warmups']), 2)
            self.assertEqual([pair['order'] for pair in result['workloads'][name]['pairs']], ['OD', 'DO']*4)
        self.assertFalse(result['subtract_probe_cost'])
        EVIDENCE.append(dict(case='C_provided_synthetic_records', status=result['status'],
            workloads=2, probe_samples_each=4097, formal_pairs_each=8, warmups_each=2,
            live_measurement_executed=False))

    def test_probe_missing_counts_clock_calls_and_output_scope_cannot_pass(self):
        cases = ('count', 'missing', 'clock', 'scope', 'trace', 'namespace', 'component')
        for case in cases:
            record = overhead_fixture()
            if case == 'count': record['probes']['empty_stamp'].pop()
            elif case == 'missing': record['probes']['full_recording'][0]['dispatch_ns'] = None
            elif case == 'clock': record['probes']['full_recording'][0]['clock_reads']['cpu'] = 0
            elif case == 'scope': record['workloads'][0]['rows'][0]['outer_includes_output'] = False
            elif case == 'trace': record['workloads'][0]['rows'][0]['trace_sha256'] = 'e'*64
            elif case == 'namespace': record['workloads'][0]['rows'][1]['namespace'] = record['workloads'][0]['rows'][0]['namespace']
            else: record['probes']['full_recording'][0]['append_ns'] = 31
            result = evaluate_artificial_overhead(record)
            self.assertIn(result['status'], ('rejected_structure', 'perturbation_not_accepted'))
            self.assertEqual(result['records'], record)

    def test_workload_deadline_and_sequential_elapsed_cannot_hide_cost(self):
        for elapsed, status in ((120_000_000_000, 'artificial_perturbation_passed'),
            (120_000_000_001, 'perturbation_not_accepted'), (0, 'rejected_structure')):
            record = overhead_fixture(); record['workloads'][0]['elapsed_wall_ns'] = elapsed
            self.assertEqual(evaluate_artificial_overhead(record)['status'], status)

    def test_c_missing_warmup_bad_order_and_failed_prerequisite_do_not_pass(self):
        record = overhead_fixture(); record['workloads'][1]['rows'][0]['wall_ns'] = None
        result = evaluate_artificial_overhead(record)
        self.assertEqual(result['status'], 'perturbation_not_accepted')
        self.assertEqual(result['workloads']['sleep']['gate']['valid_pairs'], 8)
        record = overhead_fixture(); record['workloads'][1]['rows'][2:4] = reversed(record['workloads'][1]['rows'][2:4])
        self.assertEqual(evaluate_artificial_overhead(record)['status'], 'rejected_structure')
        record = overhead_fixture(); record['capability']['clocks']['cpu']['resolution_seconds'] = '0.001'
        self.assertEqual(evaluate_artificial_overhead(record)['status'], 'cpu_resolution_insufficient')


class WindowDecisionTests(unittest.TestCase):
    def test_complete_window_keeps_28_entries_56_calibrations_and_14_metrics(self):
        record = window_fixture()
        result = evaluate_window(record)
        self.assertEqual(result['status'], 'window_perturbation_passed')
        self.assertEqual((result['formal_pairs'], result['formal_entries'], result['warm_entries'], result['calibration_count']), (12, 24, 4, 56))
        self.assertEqual([row['label'] for row in result['warmups']], ['warm_V39_O', 'warm_V46_D', 'warm_V46_O', 'warm_V39_D'])
        self.assertEqual(result['local_subset_ordinals'], [31, 32])
        for decoder in ('V39', 'V46'):
            self.assertEqual(len(result['decoders'][decoder]), 7)
            for metric in result['decoders'][decoder].values():
                self.assertTrue(metric['passed'])
                self.assertEqual((metric['valid_pairs'], metric['missing_pairs']), (6, 0))
                self.assertEqual([pair['order'] for pair in metric['pairs']], ['OD', 'DO']*3)
        self.assertFalse(result['live_B_C_D_passed'])
        self.assertFalse(result['live_measurement_executed'])
        self.assertEqual(result['original_entry_metric'], METRIC_SOURCE)
        EVIDENCE.append(dict(case='D_provided_synthetic_records', status=result['status'],
            formal_pairs=12, formal_entries=24, warm_entries=4, calibrations=56,
            global_metric_groups=6, local_metric_groups=8, live_measurement_executed=False))

    def test_global_absolute_ratio_exact_median_and_maximum_edges(self):
        for deltas, passed in (([20_000_000]*5+[50_000_000], True),
                              ([20_000_001]*6, False), ([0]*5+[50_000_001], False)):
            record = window_fixture()
            for block, delta in enumerate(deltas, 1):
                instrumentation_value(record, formal(record, 'V39', block, 'D'), 1_000_000_000+delta)
            result = evaluate_window(record)
            metric = result['decoders']['V39']['instrumentation_entry_ns']
            self.assertIs(metric['passed'], passed)
            self.assertEqual(result['status'], 'window_perturbation_passed' if passed else 'perturbation_not_accepted')

    def test_signed_changes_cannot_cancel_absolute_global_budget(self):
        record = window_fixture()
        for block, delta in enumerate((30_000_000, -30_000_000)*3, 1):
            instrumentation_value(record, formal(record, 'V46', block, 'D'), 1_000_000_000+delta)
        result = evaluate_window(record)
        metric = result['decoders']['V46']['instrumentation_entry_ns']
        self.assertEqual(metric['signed_delta_ns']['median'], 0)
        self.assertEqual(metric['absolute']['median_exact'], dict(numerator=3, denominator=100))
        self.assertFalse(metric['passed'])

    def test_local_abs_edges_zero_original_and_both_display_positions(self):
        for deltas, passed in (([100_000]*5+[500_000], True),
                              ([100_001]*6, False), ([0]*5+[500_001], False)):
            record = window_fixture()
            for block, delta in enumerate(deltas, 1):
                for ordinal in (31, 32):
                    formal(record, 'V39', block, 'O')['metrics'][PHASES[0]][ordinal] = 0
                    formal(record, 'V39', block, 'D')['metrics'][PHASES[0]][ordinal] = delta
            result = evaluate_window(record)
            for display in (32, 33):
                metric = result['decoders']['V39'][f'{display}:{PHASES[0]}']
                self.assertIs(metric['passed'], passed)
                self.assertEqual(metric['pairs'][0]['O'], 0)
            self.assertEqual(result['decoders']['V46'][f'32:{PHASES[0]}']['absolute']['max'], 0)

    def test_each_global_and_each_decoder_local_gate_is_required(self):
        for decoder, metric in (('V39', 'original_entry_ns'), ('V46', 'query_sum_ns'),
                                ('V46', f'33:{PHASES[1]}')):
            record = window_fixture()
            for block in range(1, 7):
                row = formal(record, decoder, block, 'D')
                if metric == 'original_entry_ns': row['metrics']['original_entry_ns'] += 27_000_000
                elif metric == 'query_sum_ns': row['metrics']['query_wall_ns'][0] += 15_000_000
                else: row['metrics'][PHASES[1]][32] += 100_001
            result = evaluate_window(record)
            self.assertEqual(result['status'], 'perturbation_not_accepted')
            self.assertFalse(result['decoders'][decoder][metric]['passed'])

    def test_missing_values_remain_in_their_pair_without_repair(self):
        record = window_fixture()
        formal(record, 'V39', 2, 'D')['metrics']['query_wall_ns'][5] = None
        result = evaluate_window(record)
        metric = result['decoders']['V39']['query_sum_ns']
        self.assertEqual(result['status'], 'perturbation_not_accepted')
        self.assertEqual(metric['missing_pairs'], 1)
        self.assertIsNone(metric['pairs'][1]['delta_D_minus_O_ns'])
        self.assertEqual(metric['pairs'][2]['delta_D_minus_O_ns'], 0)
        self.assertEqual(len(metric['pairs']), 6)
        record = window_fixture(); formal(record, 'V39', 2, 'D')['completed'] = False
        result = evaluate_window(record)
        self.assertEqual(result['decoders']['V39']['instrumentation_entry_ns']['missing_pairs'], 1)

    def test_warmup_quality_is_required_but_not_in_formal_pair_arithmetic(self):
        record = window_fixture(); row = record['entries'][0]
        row['metrics'].update(original_entry_ns=2_500_000_000, run_total_ns=2_600_000_000)
        instrumentation_value(record, row, 3_000_000_000)
        result = evaluate_window(record)
        self.assertEqual(result['status'], 'window_perturbation_passed')
        self.assertEqual(result['decoders']['V39']['instrumentation_entry_ns']['absolute']['max'], 0)
        record['entries'][0]['completed'] = False
        self.assertEqual(evaluate_window(record)['status'], 'perturbation_not_accepted')

    def test_all_pre_post_calibrations_include_original_and_warm_entries(self):
        for index in (0, 1, 6, 7, 8, 9, 54, 55):
            record = window_fixture(); record['calibrations'][index]['capability']['completed'] = False
            result = evaluate_window(record)
            self.assertEqual(result['status'], 'clock_capability_unconfirmed')
            self.assertEqual(len(result['calibrations']), 56)
        record = window_fixture()
        for index in (8, 9):
            record['calibrations'][index]['capability']['clocks']['cpu']['resolution_seconds'] = '0.001'
        self.assertEqual(evaluate_window(record)['status'], 'cpu_resolution_insufficient')

    def test_event_bracket_limit_includes_warmup_and_missing_brackets(self):
        record = window_fixture(); record['entries'][1]['event_brackets_ns'][0] = 100_000
        self.assertEqual(evaluate_window(record)['status'], 'window_perturbation_passed')
        record['entries'][1]['event_brackets_ns'][0] = 100_001
        self.assertEqual(evaluate_window(record)['status'], 'clock_capability_unconfirmed')
        record['entries'][1]['event_brackets_ns'][0] = None
        self.assertEqual(evaluate_window(record)['status'], 'clock_capability_unconfirmed')

    def test_schedule_identity_count_and_calibration_association_reject_structure(self):
        mutations = (
            lambda r: r['entries'].pop(),
            lambda r: r['calibrations'].pop(),
            lambda r: r['entries'].__setitem__(slice(4, 6), reversed(r['entries'][4:6])),
            lambda r: r['entries'][4].update(block=True),
            lambda r: r['entries'][4]['cohort'][0].update(original_ordinal=100.0),
            lambda r: r['entries'][4]['cohort'][0].update(key_sha256='f'*64),
            lambda r: r['entries'][4].update(source_sha256='f'*64),
            lambda r: r['calibrations'][0].update(id='copied'),
            lambda r: r['calibrations'][0]['capability']['environment'].update(process_id=20),
            lambda r: r['entries'][0]['event_brackets_ns'].append(1),
            lambda r: r['entries'][4].update(namespace=r['entries'][0]['namespace']),
        )
        for mutation in mutations:
            record = window_fixture(); mutation(record)
            self.assertEqual(evaluate_window(record)['status'], 'rejected_structure')

    def test_metric_hierarchy_source_and_output_agreement_cannot_be_substituted(self):
        mutations = (
            lambda r: r['entries'][0].update(original_entry_metric='run.total'),
            lambda r: r['entries'][0]['metrics'].update(original_entry_ns=1_000_000_001),
            lambda r: r['entries'][0]['metrics']['query_wall_ns'].__setitem__(0, 1_000_000_000),
            lambda r: r['entries'][0]['metrics'][PHASES[0]].__setitem__(0, 10_000_001),
            lambda r: r['entries'][0]['agreement'].update(payload_equal=False),
            lambda r: r['entries'][0]['agreement'].update(outer_scope_verified=False),
        )
        for mutation in mutations:
            record = window_fixture(); mutation(record)
            self.assertEqual(evaluate_window(record)['status'], 'rejected_structure')

    def test_timeline_sampler_coverage_and_total_window_deadline_are_enforced(self):
        mutations = (
            lambda r: r['entries'][0]['timeline'].update(sampler_first_ns=9_000_000_000),
            lambda r: r['entries'][0]['timeline'].update(before_calibration_end_ns=2_999_999_999),
            lambda r: r['entries'][0]['timeline'].update(instrumentation_end_ns=4_000_000_101),
            lambda r: r.update(ended_wall_ns=0, elapsed_wall_ns=0),
            lambda r: r['calibrations'][2].update(capability=deepcopy(r['calibrations'][0]['capability'])),
        )
        for mutation in mutations:
            record = window_fixture(); mutation(record)
            self.assertEqual(evaluate_window(record)['status'], 'rejected_structure')
        record = window_fixture(); record.update(ended_wall_ns=1_800_000_000_000, elapsed_wall_ns=1_800_000_000_000)
        self.assertEqual(evaluate_window(record)['status'], 'window_perturbation_passed')
        record.update(ended_wall_ns=1_800_000_000_001, elapsed_wall_ns=1_800_000_000_001)
        self.assertEqual(evaluate_window(record)['status'], 'perturbation_not_accepted')

    def test_missing_nontarget_phase_prerequisite_and_detached_output(self):
        record = window_fixture(); record['entries'][4]['metrics'][PHASES[0]][0] = None
        self.assertEqual(evaluate_window(record)['status'], 'perturbation_not_accepted')
        record = window_fixture(); record['prerequisite_C']['workloads'][0]['rows'][2]['completed'] = False
        self.assertEqual(evaluate_window(record)['status'], 'perturbation_not_accepted')
        record = window_fixture(); original = deepcopy(record)
        result = evaluate_window(record)
        self.assertEqual(record, original)
        result['records']['entries'][0]['metrics']['query_wall_ns'][0] = 0
        result['warmups'][0]['cohort'][0]['original_ordinal'] = 1
        self.assertEqual(record, original)

    def test_unknown_agreement_and_same_identity_cpu_reset_cannot_pass(self):
        for completed in (True, False):
            record = window_fixture(); row = record['entries'][4]
            row['completed'] = completed
            row['agreement']['ledger_equal'] = None
            result = evaluate_window(record)
            self.assertEqual(result['status'], 'perturbation_not_accepted')
            self.assertIsNone(result['records']['entries'][4]['agreement']['ledger_equal'])
        record = window_fixture()
        # Keep each B monotonic, but reset both B calls of entry 2 below entry 1.
        for calibration in record['calibrations'][2:4]:
            cap = calibration['capability']
            adjustment = 1_000_000_000
            for dense in cap['rounds']:
                for stamp in dense['stamps']:
                    stamp['thread_cpu_ns'] -= adjustment
            for sleep in cap['sleeps']:
                for endpoint in ('start', 'end'):
                    sleep[endpoint]['thread_cpu_ns'] -= adjustment
        self.assertEqual(evaluate_window(record)['status'], 'rejected_structure')


if __name__ == '__main__':
    unittest.main()
