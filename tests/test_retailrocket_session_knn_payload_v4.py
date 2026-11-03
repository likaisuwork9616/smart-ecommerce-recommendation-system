"""Synthetic unindexed-prefix/offset parity and byte-only payload measurements."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_payload_v4 as diagnostic
from scripts import retailrocket_session_knn_sources_v4 as sources


def csv_frame(fields, terminator):
    output = io.StringIO(newline='')
    csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator=terminator).writerow(fields)
    return output.getvalue().encode('utf-8')


class PayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/'artificial.jsonl'

    def test_framing_counts_original_bytes_without_json_or_utf8_decoding(self):
        frames = [b'x'*1022+b'\r\n', b'1'*1024+b'\n', b'\xff\n', b'junk\r', b'not-json']
        self.path.write_bytes(b''.join(frames))
        with patch.object(sources, 'BLOCK', 3), patch.object(json, 'loads', side_effect=AssertionError('decoded JSON')):
            stats = diagnostic.payload_stats(self.path, len(frames), lambda: None)
        self.assertEqual(stats['total_bytes'], sum(map(len, frames)))
        self.assertEqual(stats['rows'], 5)
        self.assertEqual((stats['min_bytes'], stats['max_bytes'], stats['p50_bytes'], stats['p99_bytes']), (2, 1025, 8, 1025))
        self.assertEqual(stats['mean_bytes'], sum(map(len, frames))/5)
        self.assertEqual([b['frames'] for b in stats['histogram']], [4, 1, 0, 0, 0, 0, 0])
        self.assertTrue(stats['framing_only'])
        self.assertFalse(stats['formal_acceptance'])
        self.assertEqual(stats['source_label'], 'unaccepted_primary_payload')

    def test_percentiles_histogram_edges_and_sample_label(self):
        self.path.write_bytes(b''.join(b'x'*(n-1)+b'\n' for n in range(1, 101)))
        stats = diagnostic.payload_stats(self.path, 100, lambda: None, source_label='verified_sample')
        for percent in (50, 90, 95, 99):
            self.assertEqual(stats[f'p{percent}_bytes'], percent)
        self.assertEqual(stats['source_label'], 'verified_sample')
        self.assertTrue(stats['source_label_from_caller'])
        self.assertFalse(stats['json_values_decoded'])

    def test_empty_input_and_mismatched_expected_rows(self):
        self.path.write_bytes(b'')
        stats = diagnostic.payload_stats(self.path, 0)
        self.assertEqual(stats['total_bytes'], 0)
        self.assertIsNone(stats['p95_bytes'])
        self.assertIsNone(stats['mean_bytes'])
        with self.assertRaisesRegex(ValueError, 'Fewer physical'):
            diagnostic.payload_stats(self.path, 1)
        self.path.write_bytes(b'{}\n')
        with self.assertRaisesRegex(ValueError, 'More physical'):
            diagnostic.payload_stats(self.path, 0)
        with self.assertRaisesRegex(ValueError, 'source label'):
            diagnostic.payload_stats(self.path, 1, source_label='full_acceptance')

    def test_stats_watch_interrupts_within_scan(self):
        self.path.write_bytes(b'x\n'*200)
        calls = iter((False, False, False, True))
        def watch():
            if next(calls):
                raise TimeoutError('synthetic stop')
        with self.assertRaises(TimeoutError):
            diagnostic.payload_stats(self.path, 200, watch)


class PrefixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.primary = self.root/'primary'
        self.paths = {name: self.root/name for name in ('dataset', 'P0', 'C1', 'D1')}
        self.config = {'schemas': {'queries.csv': ['role', 'visitorid', 'session_start_ms', 'query_ms', 'target_items']},
                       'fixed_validation': {'queries': 4}}
        self.files = sources._sources(self.primary, self.paths, self.config)
        self.keys = [['1', 0, i+1] for i in range(4)]
        self.frames, self.heads = {}, {}
        for name, (path, header) in self.files.items():
            path.parent.mkdir(exist_ok=True)
            self.heads[name] = csv_frame(header, '\r\n') if header else b''
            self.frames[name] = []
            with path.open('wb') as source:
                source.write(self.heads[name])
                for ordinal, key in enumerate(self.keys):
                    ending = ('\r\n', '\n', '\r', '\n')[ordinal]
                    if name == 'dataset':
                        source.write(csv_frame(['test', 'unparseable', '?', '?', '{opaque\r\nfield'], '\r\n'))
                    if header:
                        fields = dict(role='validation', visitorid=key[0], session_start_ms=str(key[1]),
                                      query_ms=str(key[2]), target_items='非 JSON, "quoted"\r\n第二行')
                        raw = csv_frame([fields.get(col, 'unused') for col in header], ending)
                    else:
                        raw = (json.dumps({'key': key, 'comment': '人工欄位'}, ensure_ascii=False)+
                               ('' if ordinal == 3 else ending)).encode('utf-8')
                    source.write(raw)
                    self.frames[name].append(raw)
                if name == 'dataset':
                    source.write(csv_frame(['test', 'bad', 'x', 'y', 'not json'], '\r\n'))

    def scan(self, count, last_key, watch=lambda: None):
        return diagnostic.prefix_scan(self.primary, self.paths, self.config, count, last_key, watch)

    def test_prefix_matches_indexed_next_raw_bytes_and_keys_at_all_boundaries(self):
        index = self.root/'index'
        with patch.object(sources, 'BLOCK', 7):
            sealed = sources.build_source_index(index, self.primary, self.paths, self.config,
                                                [{'key': self.keys[2]}], cutpoints=(1, 3, 4))
            for count in range(5):
                with self.subTest(count=count):
                    previous = self.keys[count-1] if count else None
                    scanned = self.scan(count, previous)
                    indexed = sources.resume_sources(index, count, previous, expected_manifest_sha256=sealed['manifest_sha256'])
                    self.assertEqual(scanned['next_key'], indexed['next_key'])
                    self.assertEqual(scanned['next_record_bytes'], indexed['next_record_bytes'])
                    self.assertEqual(scanned['parsed_validation_records'], min(count+1, 4))
                    if count < 4:
                        self.assertEqual(scanned['next_record_bytes'], {n: self.frames[n][count] for n in sources.NAMES})
                    else:
                        self.assertIsNone(scanned['next_record_bytes'])
                        self.assertEqual(scanned['bytes_consumed'], sum(path.stat().st_size for path, _ in self.files.values()))
                    self.assertEqual(scanned['validation_eof_verified'], count == 4)
                    self.assertGreaterEqual(scanned['bytes_read'], scanned['bytes_consumed'])
                    self.assertFalse(scanned['ledger_verified'])
                    self.assertFalse(scanned['formal_acceptance'])

    def test_wrong_last_key_inconsistent_count_and_deadline(self):
        for count, key in [(1, ['1', 0, 9]), (0, self.keys[0]), (1, None), (5, self.keys[-1]), (True, None)]:
            with self.subTest(count=count, key=key), self.assertRaises(ValueError):
                self.scan(count, key)
        def stop():
            raise TimeoutError('synthetic deadline')
        with self.assertRaises(TimeoutError):
            self.scan(2, self.keys[1], stop)

    def test_missing_or_extra_control_rejected_even_at_eof(self):
        file = self.files['k1'][0]
        file.write_bytes(b''.join(self.frames['k1'][:-1]))
        with self.assertRaisesRegex(ValueError, 'Missing or misaligned'):
            self.scan(3, self.keys[2])
        file.write_bytes(b''.join(self.frames['k1'])+b'\n{"key":["9",0,9]}\n')
        with self.assertRaisesRegex(ValueError, 'Extra paired control'):
            self.scan(4, self.keys[3])

    def test_duplicate_or_out_of_order_aligned_rows_rejected(self):
        for name, (file, _) in self.files.items():
            file.write_bytes(self.heads[name]+self.frames[name][0]+self.frames[name][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate or unordered'):
            self.scan(1, self.keys[0])

    def test_unexpected_role_in_control_rejected(self):
        file = self.files['d1'][0]
        file.write_bytes(b'{"role":"test","key":["1",0,1]}\n')
        with self.assertRaisesRegex(ValueError, 'control JSON role'):
            self.scan(0, None)

    def test_synchronized_sources_cannot_silently_shorten_fixed_population(self):
        for name, (file, _) in self.files.items():
            file.write_bytes(self.heads[name]+b''.join(self.frames[name][:2]))
        with self.assertRaisesRegex(ValueError, 'ended before'):
            self.scan(2, self.keys[1])


if __name__ == '__main__':
    unittest.main()
