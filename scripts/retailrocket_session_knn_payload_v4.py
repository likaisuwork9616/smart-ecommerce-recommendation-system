"""Byte-shape statistics and an unindexed seven-source prefix scan for V4 diagnostics."""
from bisect import bisect_left
from contextlib import ExitStack
from pathlib import Path
from time import perf_counter

from scripts import retailrocket_session_knn_sources_v4 as sources


HISTOGRAM_UPPER_BYTES = (1024, 4096, 16384, 65536, 262144, 1048576)


def _file_stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def payload_stats(path, expected_rows, watch=lambda: None, *, source_label='unaccepted_primary_payload'):
    """Measure physical JSONL frame lengths, including terminators, without decoding.

    source_label describes the caller's input. This pass cannot verify ledger
    contents, source provenance, role labels, targets or prediction correctness.
    """
    if type(expected_rows) is not int or expected_rows < 0:
        raise ValueError('Expected a nonnegative integer frame count')
    if source_label not in ('unaccepted_primary_payload', 'verified_sample'):
        raise ValueError('Invalid caller-supplied frame source label')
    started = perf_counter()
    watch()
    path = Path(path)
    before = _file_stamp(path)
    lengths = []
    counts = [0]*(len(HISTOGRAM_UPPER_BYTES)+1)
    total = 0
    with path.open('rb') as stream:
        for raw in sources._physical(stream, watch):
            watch()
            size = len(raw)
            lengths.append(size)
            if len(lengths) > expected_rows:
                raise ValueError('More physical frames than expected')
            total += size
            counts[bisect_left(HISTOGRAM_UPPER_BYTES, size)] += 1
    if before != _file_stamp(path) or before[2] != total:
        raise ValueError('Payload file changed during frame scan')
    if len(lengths) != expected_rows:
        raise ValueError('Fewer physical frames than expected')
    lengths.sort()
    size_summary = {f'p{percent}_bytes': lengths[(percent*len(lengths)+99)//100-1] if lengths else None
                    for percent in (50, 90, 95, 99)}
    histogram = []
    lower = 0
    for upper, count in zip((*HISTOGRAM_UPPER_BYTES, None), counts):
        histogram.append({'min_inclusive_bytes': lower, 'max_inclusive_bytes': upper, 'frames': count})
        if upper is not None:
            lower = upper+1
    watch()
    return {'kind': 'physical_frame_size_statistics', 'framing_only': True, 'source_label': source_label,
            'source_label_from_caller': True, 'formal_acceptance': False, 'json_values_decoded': False,
            'frame_bytes_include_line_terminator': True, 'rows': len(lengths), 'total_bytes': total,
            'min_bytes': lengths[0] if lengths else None, 'max_bytes': lengths[-1] if lengths else None,
            'mean_bytes': total/len(lengths) if lengths else None, **size_summary,
            'quantile_method': 'nearest_rank', 'histogram': histogram, 'seconds': perf_counter()-started}


def prefix_scan(primary, paths, config, count, last_key, watch=lambda: None):
    """Read from original headers through the requested boundary, without an index.

    next_key, last_key and next_record_bytes are private local evidence. The
    partial-prefix case checks the requested prefix and one following paired
    frame. The full-prefix case checks simultaneous validation EOF in all seven
    sources. Source hashing and ledger replay are separate operations.
    """
    population = config['fixed_validation']['queries']
    if type(population) is not int or population < 0 or type(count) is not int or not 0 <= count <= population:
        raise ValueError('Invalid prefix count or fixed population')
    if (count == 0) != (last_key is None):
        raise ValueError('Prefix count and last key disagree')
    wanted = None if last_key is None else sources._key(last_key)
    started = perf_counter()
    watch()
    inputs = sources._sources(primary, paths, config)
    stamps = {name: _file_stamp(path) for name, (path, _) in inputs.items()}
    previous = following = None
    parsed = 0
    with ExitStack() as stack:
        handles, readers = {}, {}
        for name, (path, header) in inputs.items():
            handle = stack.enter_context(path.open('rb'))
            handles[name] = handle
            readers[name] = sources._Reader(handle, name, header, watch, read_header=True)
        # For non-EOF cursors, reproduce the exact next bytes from each stream.
        for ordinal in range(min(count+1, population)):
            watch()
            frames = sources._paired(readers)
            if frames is None:
                raise ValueError('Validation sources ended before requested prefix boundary')
            key = frames['dataset'][0]
            if previous is not None and key <= previous:
                raise ValueError('Duplicate or unordered source key during prefix scan')
            if ordinal == count-1 and key != wanted:
                raise ValueError('Last committed key differs from original source prefix')
            if ordinal == count:
                following = frames
            previous = key
            parsed += 1
        if count == population:
            watch()
            if sources._paired(readers) is not None:
                raise ValueError('Extra validation record after fixed population')
        # _Reader.offset counts consumed rows. tell() also counts unread bytes
        # in _physical's current block; neither value measures physical disk I/O.
        consumed = {name: reader.offset for name, reader in readers.items()}
        read_bytes = {name: handle.tell() for name, handle in handles.items()}
        for name, (path, _) in inputs.items():
            if _file_stamp(path) != stamps[name]:
                raise ValueError('Original source changed during prefix scan')
    watch()
    return {'kind': 'unindexed_original_validation_source_prefix_only', 'formal_acceptance': False,
            'ledger_verified': False, 'source_hash_included': False, 'cache_state': 'uncontrolled',
            'reserved_test': 'locked', 'committed_count': count, 'last_key': last_key,
            'next_ordinal': count if following else None, 'next_key': list(following['dataset'][0]) if following else None,
            'next_record_bytes': {name: frame[3] for name, frame in following.items()} if following else None,
            'fixed_validation_queries': population, 'validation_eof_verified': count == population,
            'parsed_validation_records': parsed, 'includes_next_record': following is not None,
            'stream_bytes_consumed': consumed, 'bytes_consumed': sum(consumed.values()),
            'stream_bytes_read': read_bytes, 'bytes_read': sum(read_bytes.values()),
            'bytes_read_interpretation': 'bytes returned to framing reader, including prefetched blocks',
            'scan_seconds': perf_counter()-started}
