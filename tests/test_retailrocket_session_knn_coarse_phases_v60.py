"""Synthetic event trees only; no historical records or workload execution."""
from copy import deepcopy
import unittest

from scripts.retailrocket_session_knn_coarse_phases_v60 import extract_phases, PHASES
from scripts.retailrocket_session_knn_sources_v24 import summarize_events
from tests.test_retailrocket_session_knn_phase_accounting_v49 import fixture, event


class CoarsePhaseTests(unittest.TestCase):
    def test_exact_seven_intervals_and_provenance(self):
        events, accounting = fixture()
        result = extract_phases(events, accounting, summarize_events(events))
        self.assertEqual((result['root_start_ns'], result['root_end_ns'], result['root_duration_ns']),
                         (0, 100_000_000_000, 100_000_000_000))
        self.assertEqual([row['name'] for row in result['phases']], list(PHASES))
        expected = [(15, 23), (24, 30), (30, 34), (38, 43), (44, 48), (53, 72), (73, 79)]
        self.assertEqual([(row['start_ns'] / 1e9, row['end_ns'] / 1e9)
                          for row in result['phases']], expected)
        for row in result['phases']:
            self.assertEqual(row['duration_ns'], row['end_ns'] - row['start_ns'])
            self.assertTrue(all(type(index) is int for index in row['source_event_ids']))
        self.assertEqual(result['phases'][0]['source_kind'], 'passive_reference_build')
        self.assertEqual(result['phases'][5]['source_kind'], 'derived_between_events')
        self.assertEqual(result['phases'][5]['source_event_ids'],
            [event(events, 'verifier.setup_envelope')['id'], event(events, 'cache.final_guard')['id']])

    def test_post_setup_envelope_is_not_primary_or_full_entry_partition(self):
        events, accounting = fixture()
        result = extract_phases(events, accounting)
        envelope = next(row for row in result['phases'] if row['name'] == 'post_setup_before_final_guard')
        self.assertEqual(envelope['duration_ns'], 19_000_000_000)
        self.assertEqual(accounting['costs']['primary_seconds'], 12)
        self.assertNotEqual(envelope['duration_ns'] / 1e9, accounting['costs']['primary_seconds'])
        self.assertLess(sum(row['duration_ns'] for row in result['phases']), result['root_duration_ns'])

    def test_input_is_unchanged_and_output_has_no_raw_metadata(self):
        events, accounting = fixture()
        before = deepcopy((events, accounting))
        result = extract_phases(events, accounting)
        self.assertEqual((events, accounting), before)
        for row in result['phases']:
            self.assertEqual(set(row), {'name', 'start_ns', 'end_ns', 'duration_ns',
                                       'source_kind', 'source_event_ids'})
        result['phases'][0]['source_event_ids'].append(999)
        self.assertEqual((events, accounting), before)

    def test_shifted_clock_preserves_original_origin_and_durations(self):
        events, accounting = fixture()
        shift = 4_000_000_000_000
        for row in events:
            row['start_ns'] += shift
            row['end_ns'] += shift
        proof = event(events, 'cache.use')['metadata']['typed_reference']
        for row in [proof['build'], *proof['checks']]:
            row['start_ns'] += shift
            row['end_ns'] += shift
        result = extract_phases(events, accounting)
        self.assertEqual(result['root_start_ns'], shift)
        self.assertEqual(result['phases'][0]['start_ns'], shift + 15_000_000_000)
        self.assertEqual(result['phases'][5]['duration_ns'], 19_000_000_000)

    def test_zero_passive_interval_is_preserved_and_negative_is_rejected(self):
        events, accounting = fixture()
        build = event(events, 'cache.use')['metadata']['typed_reference']['build']
        build['end_ns'] = build['start_ns']
        result = extract_phases(events, accounting)
        self.assertEqual(result['phases'][0]['duration_ns'], 0)
        build['end_ns'] -= 1
        with self.assertRaises(ValueError):
            extract_phases(events, accounting)

    def test_missing_duplicate_owner_and_passive_corruption_fail_closed(self):
        for change in ('missing', 'duplicate', 'owner', 'passive', 'root', 'boundary'):
            events, accounting = fixture()
            if change == 'missing':
                event(events, 'cache.original_load_context')['phase'] = 'cache.original_prepare_catalog'
            elif change == 'duplicate':
                row = deepcopy(event(events, 'cache.original_load_context'))
                row['id'] = len(events)
                events.append(row)
            elif change == 'owner':
                event(events, 'snapshot.fingerprint')['parent'] = event(events, 'cache.pre_use_digest')['id']
            elif change == 'passive':
                event(events, 'cache.use')['metadata']['typed_reference']['build']['end_ns'] = 25_000_000_000
            elif change == 'root':
                events[0]['end_ns'] = 80_000_000_000
            else:
                event(events, 'cache.final_guard')['start_ns'] = 50_000_000_000
            with self.subTest(change=change), self.assertRaises(ValueError):
                extract_phases(events, accounting)

    def test_original_diagnostic_and_accounting_must_reconcile(self):
        events, accounting = fixture()
        diagnostic = summarize_events(events)
        diagnostic['root_wall_ns'] += 1
        with self.assertRaises(ValueError):
            extract_phases(events, accounting, diagnostic)
        accounting['primary_parts_seconds']['verification_seconds'] += 1
        with self.assertRaises(ValueError):
            extract_phases(events, accounting)


if __name__ == '__main__':
    unittest.main()
