"""Synthetic source integrity and observation checks; no real experiments."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_entry_load_v59 as analysis


def fixture():
    process = dict(pid=123, create_time=1.0, name='synthetic', cpu_user_seconds=0.,
                   cpu_system_seconds=0., rss_bytes=100, status='observed')
    records = []
    for index in range(3):
        records.append(dict(sequence=index, repeat_index=0, kind=('start', 'periodic', 'end')[index],
            monotonic_seconds=float(index), observed_utc=f'2026-01-01T00:00:0{index}+00:00',
            collector_seconds=.01, system_cpu_percent=None if index == 0 else 10. * index,
            logical_cpus=8, memory=dict(total_bytes=1000, available_bytes=600, used_bytes=400, percent=40.),
            disk_io=dict(read_bytes=index * 20, write_bytes=index * 10), disk_io_status='ok',
            worker=dict(process, cpu_user_seconds=.1 * index), ollama=[], ollama_scan_status='ok'))
    raw = dict(label='pair_1_R', mode='R', records=records)
    span = dict(label='pair_1_R', mode='R', completed=True, repeat_index=0,
                start_monotonic_seconds=.1, end_monotonic_seconds=1.9,
                start_utc='2026-01-01T00:00:00.1+00:00', end_utc='2026-01-01T00:00:01.9+00:00')
    events = [dict(phase='run.total', completed=True, start_ns=200000000, end_ns=1800000000)]
    request = dict(created_utc='2026-01-01T00:00:00+00:00', deadline_utc='2026-01-01T00:01:00+00:00')
    return raw, span, events, analysis.summarize_telemetry(records, 0), request


def checked(value):
    raw, span, events, load, request = value
    return analysis.check_observation(raw, span, events, load, 'pair_1_R', 'R', request)


class ObservationTests(unittest.TestCase):
    def test_rebuild_uses_saved_values_without_live_sampling(self):
        value = fixture()
        before = deepcopy(value)
        with patch('psutil.Process', side_effect=AssertionError('No live process read')), \
                patch('psutil.cpu_percent', side_effect=AssertionError('No live CPU read')), \
                patch('psutil.disk_io_counters', side_effect=AssertionError('No live disk read')):
            result = checked(value)
        self.assertEqual(value, before)
        self.assertTrue(result['summary_reproduced'])
        self.assertEqual(result['samples'], 3)
        self.assertAlmostEqual(result['span_seconds'], 1.8)
        self.assertEqual(value[3]['system_cpu_percent']['mean'], 15.)
        self.assertEqual(value[3]['worker']['cpu_core_percent']['mean'], 10.)

    def test_modified_summary_is_rejected(self):
        value = fixture()
        value[3]['system_cpu_percent']['mean'] += 1
        with self.assertRaises(ValueError):
            checked(value)

    def test_wrong_identity_completion_and_bounds_are_rejected(self):
        for mutation in ('label', 'arm', 'completion', 'span_start', 'span_end', 'event', 'utc', 'utc_bracket'):
            value = fixture()
            raw, span, events, _, request = value
            if mutation == 'label': raw['label'] = 'pair_2_R'
            elif mutation == 'arm': span['mode'] = 'C'
            elif mutation == 'completion': span['completed'] = False
            elif mutation == 'span_start': span['start_monotonic_seconds'] = 0.
            elif mutation == 'span_end': span['end_monotonic_seconds'] = 2.1
            elif mutation == 'event': events[0]['end_ns'] = 2100000000
            elif mutation == 'utc_bracket': raw['records'][0]['observed_utc'] = '2026-01-01T00:00:00.2+00:00'
            else: request['deadline_utc'] = '2026-01-01T00:00:01+00:00'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checked(value)

    def test_raw_counter_reset_is_retained_not_filled_or_bridged(self):
        value = fixture()
        records = value[0]['records']
        records[2]['worker']['cpu_user_seconds'] = .05
        records[2]['disk_io']['read_bytes'] = 0
        rebuilt = analysis.summarize_telemetry(records, 0)
        self.assertEqual(rebuilt['worker']['discontinuous_cpu_intervals'], 1)
        self.assertEqual(rebuilt['worker']['valid_cpu_intervals'], 1)
        self.assertEqual(rebuilt['disk_unavailable_or_reset_intervals'], 1)
        self.assertEqual(rebuilt['disk_io_delta']['read_bytes'], 20)
        checked((*value[:3], rebuilt, value[4]))

    def test_publisher_is_checked_under_its_own_identity(self):
        raw, span, events, load, request = fixture()
        raw.update(label='publisher', mode='publisher')
        span.update(label='publisher', mode='publisher')
        events[0]['phase'] = 'publisher.total'
        result = analysis.check_observation(raw, span, events, load, 'publisher', 'publisher', request)
        self.assertTrue(result['bracketing_passed'])


class SealedReaderTests(unittest.TestCase):
    def test_verified_json_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'record.json'
            data = b'{"value": 3}\n'
            path.write_bytes(data)
            record = dict(path='record.json', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            reader = analysis.SealedReader(folder, [record])
            self.assertEqual(reader.read('record.json'), {'value': 3})
            self.assertEqual(reader.checked, {'record.json': record})
            path.write_bytes(data.replace(b'3', b'4'))
            with self.assertRaises(ValueError): reader.read('record.json')

    def test_duplicate_and_outside_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            record = dict(path='../outside.json', bytes=0, sha256='0' * 64)
            with self.assertRaises(ValueError): analysis.SealedReader(folder, [record, record])
            reader = analysis.SealedReader(folder, [record])
            with self.assertRaises(ValueError): reader.read('../outside.json')

    def test_publication_is_exclusive_and_rejects_nan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            analysis.write_new(path, dict(status='ok'))
            before = path.read_bytes()
            with self.assertRaises(FileExistsError): analysis.write_new(path, dict(status='changed'))
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError): analysis.write_new(Path(folder) / 'bad.json', dict(x=float('nan')))
            self.assertFalse((Path(folder) / 'bad.json').exists())


if __name__ == '__main__':
    unittest.main()
