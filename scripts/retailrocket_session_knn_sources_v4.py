"""Sealed byte offsets for the seven validation streams. Source positioning only."""
from bisect import bisect_right
from contextlib import ExitStack
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
from time import perf_counter

from scripts.retailrocket_popularity_oracle import FIELDS, num
from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json, encoded


NAMES = ('dataset', 'p0_rank', 'p0_metrics', 'p0_slices', 'c1', 'd1', 'k1')
NEWLINE = re.compile(br'\r\n|\r|\n')
BLOCK = 1024 * 1024
STRIDE = 64


def _physical(stream, watch):
    """Yield exact physical lines, including CRLF split across two blocks."""
    pieces = []
    carry = b''
    while block := stream.read(BLOCK):
        watch()
        data = carry + block
        carry = b'\r' if data.endswith(b'\r') else b''
        if carry:
            data = data[:-1]
        start = 0
        for endmark in NEWLINE.finditer(data):
            end = endmark.end()
            fragment = data[start:end]
            if pieces:
                pieces.append(fragment)
                yield b''.join(pieces)
                pieces.clear()
            else:
                yield fragment
            start = end
        if start < len(data):
            pieces.append(data[start:])
    if carry or pieces:
        yield b''.join(pieces) + carry


def _key(values):
    if (type(values) is not list or len(values) != 3 or type(values[0]) is not str
            or any(type(value) is not int or value < 0 for value in values[1:])):
        raise ValueError('Invalid validation key')
    num(values[0])
    return tuple(values)


class _Reader:
    def __init__(self, handle, name, header, watch, *, start=0, read_header=False, digest=None):
        self.name = name
        self.header = header
        self.offset = start
        self.digest = digest
        self.fragments = []
        self.header_raw = b''
        self.lines = _physical(handle, watch)
        if header is not None:
            self.csv = csv.reader(self._text_lines(), strict=True)
            if read_header:
                if next(self.csv, None) != header:
                    raise ValueError('Invalid CSV schema: ' + name)
                self.header_raw = b''.join(self.fragments)
                self.fragments.clear()

    def _consume(self, raw):
        self.offset += len(raw)
        if self.digest is not None:
            self.digest.update(raw)

    def _text_lines(self):
        for raw in self.lines:
            self._consume(raw)
            self.fragments.append(raw)
            yield raw.decode('utf-8')

    def next_frame(self):
        while True:
            start = self.offset
            if self.header is None:
                raw = next(self.lines, None)
                if raw is None:
                    return None
                self._consume(raw)
                row = json.loads(raw.decode('utf-8'))
                if type(row) is not dict or row.get('role', 'validation') != 'validation':
                    raise ValueError('Unexpected control JSON role or type')
                key = _key(row['key'])
            else:
                fields = next(self.csv, None)
                if fields is None:
                    return None
                raw = b''.join(self.fragments)
                self.fragments.clear()
                if not fields:  # csv.DictReader skips empty logical records.
                    continue
                if len(fields) != len(self.header):
                    raise ValueError('Invalid CSV record width: ' + self.name)
                row = dict(zip(self.header, fields))
                if row['role'] != 'validation':
                    if self.name == 'dataset':
                        continue  # Never interpret another role's identifiers or target fields.
                    raise ValueError('Unexpected P0 role')
                key = _key([row['visitorid'], num(row['session_start_ms']), num(row['query_ms'])])
            return key, start, self.offset, raw


def _sources(primary, paths, config):
    p0 = Path(paths['P0'])
    names = ('ranked_queries.csv', 'query_metrics.csv', 'query_slices.csv')
    files = [Path(paths['dataset']) / 'queries.csv', *(p0 / name for name in names),
             Path(paths['C1']) / 'queries.jsonl', Path(paths['D1']) / 'queries.jsonl',
             Path(primary) / 'queries.jsonl']
    headers = [config['schemas']['queries.csv'], *(FIELDS[name] for name in names), None, None, None]
    return {name: (path.resolve(), header) for name, path, header in zip(NAMES, files, headers)}


def _descriptor(path, root, watch):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(BLOCK):
            watch()
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('File changed during hashing')
    return {'path': path.relative_to(root).as_posix(), 'bytes': after.st_size, 'sha256': digest.hexdigest()}


def _safe(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError('Unsafe source-index path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Source-index path escapes root')
    return path


def _paired(readers):
    frames = {name: readers[name].next_frame() for name in NAMES}
    first = frames['dataset']
    if first is None:
        if any(frame is not None for frame in frames.values()):
            raise ValueError('Extra paired control at validation EOF')
        return None
    if any(frame is None or frame[0] != first[0] for frame in frames.values()):
        raise ValueError('Missing or misaligned validation control')
    return frames


def _flush(stream):
    stream.flush()
    os.fsync(stream.fileno())


def build_source_index(index_folder, primary, paths, config, frozen_probes, watch=lambda: None, *, cutpoints=()):
    """Scan source identities, copy selected original bytes, then publish the seal."""
    folder = Path(index_folder).resolve()
    sources = _sources(primary, paths, config)
    root = Path(os.path.commonpath([path.parent for path, _ in sources.values()]))
    expected = config['fixed_validation']['queries']
    if type(expected) is not int or expected < 1:
        raise ValueError('Expected a positive validation population')
    wanted = [_key(row['key']) for row in frozen_probes]
    if len(wanted) > 64 or len(wanted) != len(set(wanted)):
        raise ValueError('Invalid frozen subset')
    cuts = list(cutpoints)
    if any(type(value) is not int or not 0 <= value <= expected for value in cuts):
        raise ValueError('Invalid source cutpoint')
    special = set(cuts) | {expected - 1}
    wanted = set(wanted)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'samples').mkdir()
    sampled, source_records, sample_files = [], {}, {}
    roster = hashlib.sha256()
    anchors = count = sample_bytes = 0
    previous = None
    with ExitStack() as stack:
        readers, copies, starts, sample_paths = {}, {}, {}, {}
        index_file = stack.enter_context((folder / 'offsets.jsonl').open('xb'))
        for name, (path, header) in sources.items():
            starts[name] = path.stat()
            handle = stack.enter_context(path.open('rb'))
            readers[name] = _Reader(handle, name, header, watch, read_header=True, digest=hashlib.sha256())
            sample_paths[name] = folder / 'samples' / (name + path.suffix)
            copies[name] = stack.enter_context(sample_paths[name].open('xb'))
            copies[name].write(readers[name].header_raw)
        while (frames := _paired(readers)) is not None:
            watch()
            key = frames['dataset'][0]
            if count >= expected or previous is not None and key <= previous:
                raise ValueError('Extra, duplicate or unordered validation row')
            selected = key in wanted
            if selected:
                sampled.append(count)
                for name, (_, _, _, raw) in frames.items():
                    copies[name].write(raw)
                    sample_bytes += len(raw)
            if selected or count % STRIDE == 0 or count in special:
                spans = {name: [start, end, hashlib.sha256(raw).hexdigest()]
                         for name, (_, start, end, raw) in frames.items()}
                index_file.write(encoded({'ordinal': count, 'key': key, 'spans': spans}))
                anchors += 1
            roster.update(encoded(list(key)))
            previous = key
            count += 1
        if count != expected or len(sampled) != len(wanted):
            raise ValueError('Incomplete validation EOF or missing frozen key')
        for name, (path, header) in sources.items():
            after = path.stat()
            before = starts[name]
            reader = readers[name]
            if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                    or reader.offset != after.st_size):
                raise ValueError('Original source changed during indexing')
            source_records[name] = {'path': path.relative_to(root).as_posix(), 'bytes': reader.offset,
                                    'sha256': reader.digest.hexdigest(), 'header': header,
                                    'header_bytes': len(reader.header_raw),
                                    'header_sha256': hashlib.sha256(reader.header_raw).hexdigest()}
            _flush(copies[name])
        _flush(index_file)
    for name, path in sample_paths.items():
        sample_files[name] = _descriptor(path, folder, watch)
    manifest = {'kind': 'validation_source_position_index_only', 'version': 1, 'stride': STRIDE,
                'source_root': str(root), 'sources': source_records, 'samples': sample_files,
                'index': _descriptor(folder / 'offsets.jsonl', folder, watch), 'cutpoints': sorted(set(cuts)),
                'validation_queries': count, 'anchor_count': anchors, 'sampled_ordinals': sampled,
                'sampled_queries': len(sampled), 'raw_sample_bytes': sample_bytes,
                'roster_sha256': roster.hexdigest(), 'formal_acceptance': False, 'reserved_test': 'locked'}
    watch()
    atomic_json(folder / 'manifest.json', manifest)
    manifest_record = _descriptor(folder / 'manifest.json', folder, watch)
    watch()
    atomic_json(folder / 'seal.json', {'manifest': manifest_record})
    return dict(manifest, index_folder=str(folder), manifest_sha256=manifest_record['sha256'])


def _check_file(root, record, watch):
    path = _safe(root, record['path'])
    if _descriptor(path, root, watch) != {key: record[key] for key in ('path', 'bytes', 'sha256')}:
        raise ValueError('Bound file identity changed: ' + record['path'])
    return path


def _position(handles, source_records, anchor, watch):
    readers = {}
    for name in NAMES:
        start = anchor['spans'][name][0]
        handles[name].seek(start)
        readers[name] = _Reader(handles[name], name, source_records[name]['header'], watch, start=start)
    return readers


def _validate_anchors(anchors, handles, manifest, watch):
    n = manifest['validation_queries']
    required = set(range(0, n, STRIDE)) | {n - 1} | set(manifest['sampled_ordinals'])
    required.update(c for c in manifest['cutpoints'] if c < n)
    if ([row['ordinal'] for row in anchors] != sorted(required)
            or len(anchors) != manifest['anchor_count'] or manifest['stride'] != STRIDE):
        raise ValueError('Incomplete or unordered sparse anchor roster')
    prior_end = {name: manifest['sources'][name]['header_bytes'] for name in NAMES}
    previous = None
    for anchor in anchors:
        watch()
        key = _key(anchor['key'])
        if previous is not None and key <= previous or set(anchor['spans']) != set(NAMES):
            raise ValueError('Invalid anchor key order or stream roster')
        for name in NAMES:
            start, end, expected_hash = anchor['spans'][name]
            source = manifest['sources'][name]
            if (type(start) is not int or type(end) is not int
                    or not prior_end[name] <= start < end <= source['bytes']):
                raise ValueError('Invalid or overlapping anchor byte span')
            if start:
                handles[name].seek(start - 1)
                boundary = handles[name].read(2)
                if boundary[:1] not in (b'\r', b'\n') or boundary == b'\r\n':
                    raise ValueError('Anchor begins inside a physical line or CRLF')
            handles[name].seek(start)
            raw = handles[name].read(end - start)
            if len(raw) != end - start or hashlib.sha256(raw).hexdigest() != expected_hash:
                raise ValueError('Anchor byte range SHA mismatch')
            if end < source['bytes'] and (raw[-1:] not in (b'\r', b'\n')
                    or raw.endswith(b'\r') and handles[name].read(1) == b'\n'):
                raise ValueError('Anchor ends inside a physical line or CRLF')
            reader = _Reader(io.BytesIO(raw), name, source['header'], watch, start=start)
            frame = reader.next_frame()
            if frame is None or frame[:3] != (key, start, end) or reader.next_frame() is not None:
                raise ValueError('Anchor does not frame one complete matching source row')
            prior_end[name] = end
        previous = key


def resume_sources(index_folder, committed_count, last_key, watch=lambda: None, *, expected_manifest_sha256=None):
    """Verify the complete sealed index, then read the boundary at a supplied count.

    The caller independently verifies the ledger supplying committed_count and
    last_key. This function never creates or accepts a query checkpoint. Its
    next_record_bytes are private source evidence and must not enter a report.
    """
    started = perf_counter()
    folder = Path(index_folder).resolve()
    seal = json.loads((folder / 'seal.json').read_bytes())['manifest']
    if seal['path'] != 'manifest.json' or (expected_manifest_sha256 is not None
                                            and seal['sha256'] != expected_manifest_sha256):
        raise ValueError('Unexpected source index seal')
    manifest = json.loads(_check_file(folder, seal, watch).read_bytes())
    if manifest['kind'] != 'validation_source_position_index_only' or manifest['version'] != 1:
        raise ValueError('Unexpected source index protocol')
    n = manifest['validation_queries']
    if type(committed_count) is not int or not 0 <= committed_count <= n:
        raise ValueError('Invalid committed count')
    if (committed_count == 0) != (last_key is None):
        raise ValueError('Committed count and last key disagree')
    expected_last = None if last_key is None else _key(last_key)
    root = Path(manifest['source_root']).resolve()
    records = manifest['sources']
    if set(records) != set(NAMES) or set(manifest['samples']) != set(NAMES):
        raise ValueError('Incomplete source index stream roster')
    offsets = _check_file(folder, manifest['index'], watch)
    with offsets.open('rb') as stream:
        anchors = [json.loads(line) for line in stream]
    for sample in manifest['samples'].values():
        _check_file(folder, sample, watch)
    files_checked = perf_counter()
    source_paths = {name: _safe(root, records[name]['path']) for name in NAMES}
    original_stats = {name: path.stat() for name, path in source_paths.items()}
    for name in NAMES:
        _check_file(root, records[name], watch)
    sources_checked = perf_counter()
    with ExitStack() as stack:
        handles = {name: stack.enter_context(path.open('rb')) for name, path in source_paths.items()}
        for name, handle in handles.items():
            source = records[name]
            header = _Reader(handle, name, source['header'], watch, read_header=True).header_raw
            if len(header) != source['header_bytes'] or hashlib.sha256(header).hexdigest() != source['header_sha256']:
                raise ValueError('Source header bytes changed')
        _validate_anchors(anchors, handles, manifest, watch)
        # Check actual EOF even when the requested cursor is near the beginning.
        end_readers = _position(handles, records, anchors[-1], watch)
        final = _paired(end_readers)
        if final is None or list(final['dataset'][0]) != anchors[-1]['key'] or _paired(end_readers) is not None:
            raise ValueError('Final anchor does not precede validation EOF')
        anchors_checked = perf_counter()
        ordinals = [row['ordinal'] for row in anchors]
        anchor = anchors[bisect_right(ordinals, max(0, committed_count - 1)) - 1]
        readers = _position(handles, records, anchor, watch)
        following = previous = None
        replayed = 0
        for ordinal in range(anchor['ordinal'], min(committed_count + 1, n)):
            watch()
            frame = _paired(readers)
            if frame is None:
                raise ValueError('Unexpected EOF positioning validation cursor')
            key = frame['dataset'][0]
            if (ordinal == anchor['ordinal'] and list(key) != anchor['key']
                    or previous is not None and key <= previous):
                raise ValueError('Invalid source key while positioning')
            if ordinal == committed_count - 1 and key != expected_last:
                raise ValueError('Last committed key differs from source ordinal')
            if ordinal == committed_count:
                following = frame
            previous = key
            replayed += 1
        if committed_count == n and _paired(readers) is not None:
            raise ValueError('Unexpected controls past final committed record')
        for name, path in source_paths.items():
            before = original_stats[name]
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError('Original source changed while positioning')
    watch()
    return {'kind': 'validation_source_position_only', 'formal_acceptance': False,
            'committed_count': committed_count, 'last_key': last_key,
            'next_ordinal': committed_count if following else None,
            'next_key': list(following['dataset'][0]) if following else None,
            'next_record_bytes': {name: frame[3] for name, frame in following.items()} if following else None,
            'manifest_sha256': seal['sha256'], 'anchor_ordinal': anchor['ordinal'],
            'replayed_validation_rows': replayed, 'anchors_verified': len(anchors),
            'source_bytes_hashed': sum(source['bytes'] for source in records.values()),
            'index_and_sample_hash_seconds': files_checked - started,
            'source_hash_seconds': sources_checked - files_checked,
            'anchor_and_eof_seconds': anchors_checked - sources_checked,
            'seek_seconds': perf_counter() - anchors_checked}
