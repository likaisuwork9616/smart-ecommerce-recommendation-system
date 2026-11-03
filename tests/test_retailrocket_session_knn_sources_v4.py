"""Synthetic validation source framing, index integrity and cursor recovery."""
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_sources_v4 as sources


def csv_line(fields, ending):
    output = io.StringIO(newline='')
    csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator=ending).writerow(fields)
    return output.getvalue().encode('utf-8')


class SourceTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / 'shop-mysql-runtime' / 'verification'
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base, prefix='v4-source-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / 'index'
        self.paths = {name: self.root / name for name in ('dataset', 'P0', 'C1', 'D1')}
        self.primary = self.root / 'primary'
        self.n = 131
        self.config = {'fixed_validation': {'queries': self.n}, 'schemas': {'queries.csv':
            ['role', 'visitorid', 'session_start_ms', 'query_ms', 'target_items']}}
        self.files = sources._sources(self.primary, self.paths, self.config)
        self.frames = {name: [] for name in sources.NAMES}
        self.headers = {}
        for name, (path, header) in self.files.items():
            path.parent.mkdir(exist_ok=True)
            self.headers[name] = csv_line(header, '\r\n') if header else b''
            with path.open('wb') as stream:
                stream.write(self.headers[name])
                for ordinal in range(self.n):
                    ending = ('\r\n', '\n', '\r')[ordinal % 3]
                    if name == 'dataset' and ordinal % 4 == 0:
                        # Non-validation keys and target strings must never be interpreted.
                        stream.write(csv_line(['test', 'opaque', '-', '-', '{unread'], ending))
                    if header:
                        values = {'role': 'validation', 'visitorid': '1', 'session_start_ms': '1',
                                  'query_ms': str(ordinal + 10), 'target_items': '漢字,"x"\r\n第二行'}
                        raw = csv_line([values.get(field, 'unread') for field in header], ending)
                    else:
                        raw = (' { "key" : ' + json.dumps(self.key(ordinal)) + ', "text" : "漢字" }'
                               + (ending if ordinal + 1 < self.n else '')).encode('utf-8')
                    stream.write(raw)
                    self.frames[name].append(raw)
                if name == 'dataset':
                    stream.write(csv_line(['train', 'opaque', '-', '-', 'not-json'], '\n'))

    @staticmethod
    def key(ordinal):
        return ['1', 1, ordinal + 10]

    def build(self, **kwargs):
        return sources.build_source_index(self.folder, self.primary, self.paths, self.config,
            [{'key': self.key(i)} for i in (2, 81)], cutpoints=(17, self.n), **kwargs)

    def resume(self, count, **kwargs):
        return sources.resume_sources(self.folder, count, self.key(count - 1) if count else None, **kwargs)

    def rewrite_anchor(self, mutate):
        path = self.folder / 'offsets.jsonl'
        records = [json.loads(line) for line in path.read_bytes().splitlines()]
        mutate(records)
        path.write_bytes(b''.join(sources.encoded(row) for row in records))
        path = self.folder / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['index'] = sources._descriptor(self.folder / 'offsets.jsonl', self.folder, lambda: None)
        path.write_bytes(sources.encoded(manifest))
        seal = {'manifest': sources._descriptor(path, self.folder, lambda: None)}
        (self.folder / 'seal.json').write_bytes(sources.encoded(seal))

    def test_exact_raw_samples_and_entire_source_hashes_with_mixed_newlines(self):
        with patch.object(sources, 'BLOCK', 13):
            result = self.build()
        self.assertEqual(result['sampled_ordinals'], [2, 81])
        self.assertEqual(result['validation_queries'], self.n)
        self.assertFalse(result['formal_acceptance'])
        for name in sources.NAMES:
            source = self.files[name][0].read_bytes()
            self.assertEqual(result['sources'][name]['sha256'], hashlib.sha256(source).hexdigest())
            expected = self.headers[name] + self.frames[name][2] + self.frames[name][81]
            self.assertEqual((self.folder / result['samples'][name]['path']).read_bytes(), expected)
        self.assertEqual(result['raw_sample_bytes'], sum(len(self.frames[n][i])
                         for n in sources.NAMES for i in (2, 81)))

    def test_seek_zero_stride_arbitrary_and_eof_matches_original_bytes(self):
        result = self.build()
        for count in (0, 1, 17, 62, 63, 64, 65, 81, 128, 130, self.n):
            with self.subTest(count=count):
                resumed = self.resume(count, expected_manifest_sha256=result['manifest_sha256'])
                self.assertEqual(resumed['anchors_verified'], result['anchor_count'])
                self.assertLessEqual(resumed['replayed_validation_rows'], sources.STRIDE + 1)
                self.assertEqual(resumed['next_key'], self.key(count) if count < self.n else None)
                expected = {name: self.frames[name][count] for name in sources.NAMES} if count < self.n else None
                self.assertEqual(resumed['next_record_bytes'], expected)

    def test_wrong_committed_count_or_last_key_is_rejected(self):
        self.build()
        for count, key in ((0, self.key(0)), (1, None), (1, self.key(1)), (True, None),
                           (-1, None), (self.n + 1, self.key(self.n))):
            with self.subTest(count=count), self.assertRaises(ValueError):
                sources.resume_sources(self.folder, count, key)

    def test_control_key_mismatch_on_non_sampled_row_rejects_build(self):
        path = self.files['c1'][0]
        raw = self.frames['c1'][31]
        path.write_bytes(path.read_bytes().replace(raw, raw.replace(b', 41]', b', 42]')))
        with self.assertRaisesRegex(ValueError, 'misaligned'):
            self.build()
        self.assertFalse((self.folder / 'seal.json').exists())

    def test_extra_control_at_eof_refused(self):
        path = self.files['d1'][0]
        with path.open('ab') as stream:
            stream.write(b'\n{"key":["1",1,9999]}\n')
        with self.assertRaisesRegex(ValueError, 'Extra paired'):
            self.build()

    def test_only_validation_p0_controls_allowed(self):
        path = self.files['p0_rank'][0]
        path.write_bytes(path.read_bytes().replace(b'"validation"', b'"test"', 1))
        with self.assertRaisesRegex(ValueError, 'P0 role'):
            self.build()

    def test_corrupted_csv_header_refused(self):
        path = self.files['dataset'][0]
        path.write_bytes(path.read_bytes().replace(b'visitorid', b'visitor_id', 1))
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.build()

    def test_partial_build_has_no_seal_and_cannot_overwrite(self):
        calls = 0
        def stop():
            nonlocal calls
            calls += 1
            if calls == 12:
                raise TimeoutError('synthetic interruption')
        with self.assertRaises(TimeoutError):
            self.build(watch=stop)
        with self.assertRaises(FileNotFoundError):
            self.resume(0)
        with self.assertRaises(FileExistsError):
            self.build()

    def test_bound_source_index_sample_or_manifest_tamper_fails_closed(self):
        result = self.build()
        for path in (self.files['c1'][0], self.folder / 'offsets.jsonl',
                     self.folder / result['samples']['k1']['path'], self.folder / 'manifest.json'):
            before = path.read_bytes()
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, 'identity changed'):
                path.write_bytes(bytes([before[0] ^ 1]) + before[1:])
                self.resume(8)
            path.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'seal'):
            self.resume(8, expected_manifest_sha256='0' * 64)

    def test_interior_offset_that_still_decodes_as_json_cannot_pass(self):
        self.build()
        def mutate(rows):
            # Trimming a leading space preserves parsed JSON but changes its physical boundary.
            span = rows[0]['spans']['c1']
            span[0] += 1
            span[2] = hashlib.sha256(self.frames['c1'][0][1:]).hexdigest()
        self.rewrite_anchor(mutate)
        with self.assertRaisesRegex(ValueError, 'physical line'):
            self.resume(123)

    def test_missing_sparse_anchor_rejected_even_if_requested_cursor_elsewhere(self):
        self.build()
        self.rewrite_anchor(lambda rows: rows.pop(2))
        with self.assertRaisesRegex(ValueError, 'anchor roster'):
            self.resume(0)

    def test_watch_termination_during_reentry_preserves_manifest(self):
        result = self.build()
        def stop():
            raise TimeoutError('original deadline')
        with self.assertRaises(TimeoutError):
            self.resume(88, watch=stop)
        self.assertEqual(self.resume(88)['manifest_sha256'], result['manifest_sha256'])


if __name__ == '__main__':
    unittest.main()
