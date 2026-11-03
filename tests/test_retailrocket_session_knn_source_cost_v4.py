"""Small source-only diagnostic fixtures with distinct byte spellings per stream."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_source_cost_v4 as cost
from scripts import retailrocket_session_knn_sources_v4 as sources


class SourceCostTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'shop-mysql-runtime' / 'verification'
        base.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=base, prefix='source-cost-v4-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / 'measurement'
        self.primary = self.root / 'primary'
        self.paths = {name: self.root / name for name in ('dataset', 'P0', 'C1', 'D1')}
        self.config = {'fixed_validation': {'queries': 7}, 'schemas': {'queries.csv':
            ['visitorid', 'session_start_ms', 'query_ms', 'role', 'target_items']}}
        self.probes = [{'key': ['1', 2, 14]}, {'key': ['1', 2, 10]}]  # selector order differs
        self.ordinals = [{'original_ordinal': 0, 'key': ['1', 2, 10]},
                         {'original_ordinal': 4, 'key': ['1', 2, 14]}]
        self.files = sources._sources(self.primary, self.paths, self.config)
        for name, (path, header) in self.files.items():
            path.parent.mkdir(exist_ok=True)
            with path.open('wb') as stream:
                if header:
                    stream.write((','.join(header) + '\r\n').encode())
                for i in range(7):
                    ending = ('\r', '\n', '\r\n')[i % 3]
                    if name == 'dataset' and i == 1:
                        stream.write(b'opaque,opaque,opaque,test,{unread\r\n')
                    if header:
                        values = {'role': 'validation', 'visitorid': '1', 'session_start_ms': '2',
                                  'query_ms': str(10 + i), 'target_items': '合成,"a"\r\n換行'}
                        buffer = io.StringIO(newline='')
                        csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator=ending).writerow(
                            [values.get(key, 'fixture') for key in header])
                        stream.write(buffer.getvalue().encode())
                    else:
                        stream.write(('  { "key" : ["1", 2, ' + str(10 + i) + '], "name" : "'
                                      + name + '" }' + ending).encode())

    def measure(self, ordinals=None, watch=lambda: None):
        return cost.run_source_cost(self.folder, self.primary, self.paths, self.config,
            self.probes, self.ordinals if ordinals is None else ordinals, watch)

    def phase(self, name):
        return json.loads((self.folder / 'source_cost_phases' / (name + '_receipt.json')).read_bytes())

    def test_six_real_source_boundaries_are_identical_and_distinct_from_ledger_recovery(self):
        result = self.measure()
        self.assertEqual([case['source_position'] for case in result['cases']], [0, 1, 3, 5, 6, 7])
        self.assertEqual([case['streams_with_next_frame_checked'] for case in result['cases']], [7] * 5 + [0])
        self.assertTrue(all(case['next_key_and_original_bytes_agree'] for case in result['cases']))
        total_bytes = sum(path.stat().st_size for path, _ in self.files.values())
        self.assertEqual(result['indexed_verification_source_bytes_hashed'], 6 * total_bytes)
        self.assertEqual(result['cases'][-1]['prefix']['bytes_consumed'], total_bytes)
        self.assertEqual(result['verified_ledger_records'], 0)
        self.assertFalse(result['full_real_ledger_recovery_measured'])
        self.assertFalse(result['full_readback_started'])
        self.assertIsNone(result['T_plan'])
        self.assertEqual(json.loads((self.folder / 'source_cost.json').read_bytes()), result)
        pin = json.loads((self.folder / 'binding.json').read_bytes())
        self.assertEqual((pin['sources'], pin['manifest_sha256']), (result['sources'], result['manifest_sha256']))
        self.assertEqual(len(result['phases']), 20)
        for name, receipt in result['phases'].items():
            self.assertEqual(self.phase(name), receipt)
            self.assertTrue(receipt['completed'])
            self.assertGreaterEqual(receipt['seconds'], 0)
            self.assertTrue((self.folder / 'source_cost_phases' / (name + '_started.json')).exists())
        for hidden in ('"next_key":', '"last_key":', '"next_record_bytes":', '"key":'):
            self.assertNotIn(hidden, json.dumps(result))

    def test_wrong_original_ordinals_or_keys_fail_before_any_timed_cursor(self):
        for label, roster in (('wrong_ordinals', [0, 2]), ('wrong_keys', [
                {'original_ordinal': 0, 'key': ['1', 2, 10]}, {'original_ordinal': 4, 'key': ['1', 2, 12]}])):
            with self.subTest(label=label):
                self.folder = self.root / label
                with self.assertRaisesRegex(ValueError, 'ordinal|anchor'):
                    self.measure(roster)
                self.assertFalse(self.phase('pin_source_index')['completed'])
                self.assertFalse((self.folder / 'binding.json').exists())
                self.assertFalse((self.folder / 'source_cost.json').exists())

    def test_any_unequal_raw_stream_refuses_comparison_with_equal_json_and_key(self):
        original = cost.prefix_scan
        def alter(*args):
            result = original(*args)
            result['next_record_bytes']['c1'] = b' ' + result['next_record_bytes']['c1']
            return result
        with patch.object(cost, 'prefix_scan', side_effect=alter), self.assertRaisesRegex(ValueError, 'bytes differ'):
            self.measure()
        self.assertFalse(self.phase('position_0_0_compare')['completed'])
        self.assertTrue(self.phase('position_0_0_prefix')['completed'])
        self.assertFalse((self.folder / 'source_cost.json').exists())

    def test_index_reverification_refuses_changed_source_after_durable_pin(self):
        original = sources.resume_sources
        def mutate(*args, **kwargs):
            self.assertTrue((self.folder / 'binding.json').exists())
            self.assertTrue(kwargs['expected_manifest_sha256'])
            path = self.files['d1'][0]
            path.write_bytes(path.read_bytes().replace(b'"d1"', b'"zz"', 1))
            return original(*args, **kwargs)
        with patch.object(sources, 'resume_sources', side_effect=mutate), self.assertRaisesRegex(ValueError, 'identity'):
            self.measure([0, 4])
        self.assertEqual(self.phase('position_0_0_indexed')['error_type'], 'ValueError')
        self.assertFalse((self.folder / 'source_cost.json').exists())

    def test_interrupted_prefix_keeps_prior_case_and_actual_partial_timing(self):
        original = cost.prefix_scan
        def interrupted(primary, paths, config, count, last_key, watch):
            if count == 1:
                raise TimeoutError('shared deadline reached')
            return original(primary, paths, config, count, last_key, watch)
        with patch.object(cost, 'prefix_scan', side_effect=interrupted), self.assertRaises(TimeoutError):
            self.measure()
        self.assertTrue(self.phase('position_0_0_compare')['completed'])
        receipt = self.phase('position_1_1_prefix')
        self.assertFalse(receipt['completed'])
        self.assertEqual(receipt['error_type'], 'TimeoutError')
        self.assertGreaterEqual(receipt['seconds'], 0)
        self.assertFalse((self.folder / 'source_cost.json').exists())
        before = (self.folder / 'binding.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.measure()
        self.assertEqual(before, (self.folder / 'binding.json').read_bytes())

    def test_expired_caller_watch_stops_build_before_source_work(self):
        def expired():
            raise TimeoutError('existing window expired')
        with self.assertRaises(TimeoutError):
            self.measure(watch=expired)
        self.assertFalse(self.phase('build_source_index')['completed'])
        self.assertFalse((self.folder / 'source_index').exists())


if __name__ == '__main__':
    unittest.main()
