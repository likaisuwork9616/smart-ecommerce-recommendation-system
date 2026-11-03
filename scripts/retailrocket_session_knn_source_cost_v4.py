"""Compare indexed and sequential positions in the original validation sources."""
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter, process_time

from scripts import retailrocket_session_knn_sources_v4 as sources
from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json
from scripts.retailrocket_session_knn_payload_v4 import prefix_scan


def _ordinals(rows, count, population):
    ordinals, keys = [], {}
    for row in rows:
        if isinstance(row, dict):
            ordinal = row['original_ordinal']
            if 'key' in row:
                keys[ordinal] = sources._key(row['key'])
        else:
            ordinal = row
        if type(ordinal) is not int or not 0 <= ordinal < population:
            raise ValueError('Invalid original validation ordinal')
        ordinals.append(ordinal)
    if len(set(ordinals)) != len(ordinals) or len(ordinals) != count:
        raise ValueError('Original validation ordinal roster differs')
    return sorted(ordinals), keys


def _compare(indexed, sequential, position, population):
    following = position if position < population else None
    if (indexed['next_ordinal'] != following or sequential['next_ordinal'] != following
            or indexed['next_key'] != sequential['next_key']):
        raise ValueError('Indexed and sequential source boundaries differ')
    one, two = indexed['next_record_bytes'], sequential['next_record_bytes']
    if following is None:
        if one is not None or two is not None or indexed['next_key'] is not None or not sequential['validation_eof_verified']:
            raise ValueError('Unsynchronized validation EOF')
        return {'eof': True, 'streams_with_next_frame_checked': 0, 'next_frame_bytes_checked': 0}
    if not isinstance(one, dict) or not isinstance(two, dict) or set(one) != set(sources.NAMES) or set(two) != set(sources.NAMES):
        raise ValueError('Incomplete seven-stream next frame')
    if (indexed['next_key'] is None or any(type(one[name]) is not bytes or type(two[name]) is not bytes
            or one[name] != two[name] for name in sources.NAMES)):
        raise ValueError('Indexed and sequential original source bytes differ')
    return {'eof': False, 'streams_with_next_frame_checked': len(sources.NAMES),
            'next_frame_bytes_checked': sum(len(raw) for raw in one.values())}


def run_source_cost(folder, primary, paths, config, frozen_probes, original_ordinals, watch=lambda: None):
    """Time six source-only boundaries in one caller-owned cumulative window.

    No offsets or query keys are published in the metrics. Private input
    descriptors returned here let the caller cross-check its independent frozen
    request. The caller owns the supervisor and absolute execution deadline.
    """
    started = perf_counter()
    population = config['fixed_validation']['queries']
    if type(population) is not int or population < 1:
        raise ValueError('Expected positive validation population')
    orig, supplied_keys = _ordinals(original_ordinals, len(frozen_probes), population)
    positions = [0, population // 4, population // 2, 3 * population // 4, population - 1, population]
    cuts = sorted({bound for count in positions + orig for bound in (count - 1, count) if bound >= 0})
    folder = Path(folder).resolve()
    phases_dir = folder / 'source_cost_phases'
    phases_dir.mkdir(parents=True, exist_ok=False)
    index = folder / 'source_index'
    phases = {}
    force = getattr(watch, 'force', watch)

    def timed(name, operation, summarize):
        wall = perf_counter()
        cpu = process_time()
        atomic_json(phases_dir / (name + '_started.json'), {'phase': name, 'completed': False,
                    'started_utc': datetime.now(timezone.utc).isoformat()})
        try:
            force()
            value = operation()
            metrics = summarize(value)
            force()
        except BaseException as error:
            atomic_json(phases_dir / (name + '_receipt.json'), {'phase': name, 'completed': False,
                        'error_type': type(error).__name__, 'seconds': perf_counter() - wall,
                        'cpu_seconds': process_time() - cpu})
            raise
        phases[name] = {'phase': name, 'completed': True, 'seconds': perf_counter() - wall,
                        'cpu_seconds': process_time() - cpu, 'metrics': metrics}
        atomic_json(phases_dir / (name + '_receipt.json'), phases[name])
        return value

    built = timed('build_source_index', lambda: sources.build_source_index(index, primary, paths,
        config, frozen_probes, watch, cutpoints=cuts), lambda r: {
            'validation_queries': r['validation_queries'], 'anchors': r['anchor_count'],
            'source_bytes_hashed': sum(row['bytes'] for row in r['sources'].values()),
            'raw_sample_bytes': r['raw_sample_bytes']})

    def pin():
        if built['sampled_ordinals'] != orig:
            raise ValueError('Frozen probes do not match original ordinals')
        source_index = built['index']
        offset_path = sources._check_file(index, source_index, watch)
        needed = set(orig) | {position - 1 for position in positions if position}
        keys = {}
        with offset_path.open('rb') as stream:
            for line in stream:
                watch()
                anchor = json.loads(line)
                if anchor['ordinal'] in needed:
                    keys[anchor['ordinal']] = anchor['key']
        if set(keys) != needed or any(tuple(keys[o]) != key for o, key in supplied_keys.items()):
            raise ValueError('Missing or mismatched original source anchor')
        force()
        atomic_json(folder / 'binding.json', {'scope': 'source_only_cost_measurement',
            'index_folder': 'source_index', 'manifest_sha256': built['manifest_sha256'],
            'source_root': built['source_root'], 'sources': built['sources'],
            'positions': positions, 'source_queries': population, 'formal_acceptance': False})
        return keys

    keys = timed('pin_source_index', pin, lambda _: {'manifest_sha256': built['manifest_sha256'],
                                                     'bound_sources': len(built['sources'])})
    cases = []
    indexed_keys = ('source_bytes_hashed', 'anchors_verified', 'replayed_validation_rows',
                    'index_and_sample_hash_seconds', 'source_hash_seconds', 'anchor_and_eof_seconds', 'seek_seconds')
    prefix_keys = ('bytes_consumed', 'bytes_read', 'parsed_validation_records', 'stream_bytes_consumed',
                   'stream_bytes_read', 'scan_seconds', 'validation_eof_verified', 'cache_state',
                   'bytes_read_interpretation', 'source_hash_included')
    for index_number, count in enumerate(positions):
        case = f'position_{index_number}_{count}'
        previous = keys[count - 1] if count else None
        indexed = timed(case + '_indexed', lambda: sources.resume_sources(index, count, previous, watch,
            expected_manifest_sha256=built['manifest_sha256']), lambda r: {key: r[key] for key in indexed_keys})
        sequential = timed(case + '_prefix', lambda: prefix_scan(primary, paths, config, count, previous, watch),
                           lambda r: {key: r[key] for key in prefix_keys})
        compared = timed(case + '_compare', lambda: _compare(indexed, sequential, count, population), dict)
        cases.append({'source_position': count, 'next_key_and_original_bytes_agree': True, **compared,
                      'indexed': phases[case + '_indexed']['metrics'],
                      'indexed_wall_seconds': phases[case + '_indexed']['seconds'],
                      'prefix': phases[case + '_prefix']['metrics'],
                      'prefix_wall_seconds': phases[case + '_prefix']['seconds']})
    result = {'kind': 'six_original_source_positions_cost_only', 'formal_acceptance': False,
              'verified_ledger_records': 0, 'full_real_ledger_recovery_measured': False,
              'full_readback_started': False, 'reserved_test': 'locked', 'T_plan': None,
              'validation_queries': population, 'index_folder': str(index),
              'manifest_sha256': built['manifest_sha256'], 'source_root': built['source_root'],
              'sources': built['sources'], 'anchor_count': built['anchor_count'],
              'measured_positions_preanchored': True, 'arbitrary_nonanchor_seek_cost_measured': False,
              'raw_sample_bytes': built['raw_sample_bytes'], 'cases': cases, 'phases': phases,
              'indexed_verification_source_bytes_hashed': sum(case['indexed']['source_bytes_hashed'] for case in cases),
              'prefix_bytes_consumed': sum(case['prefix']['bytes_consumed'] for case in cases),
              'prefix_bytes_read': sum(case['prefix']['bytes_read'] for case in cases),
              'cache_state': 'uncontrolled', 'seconds_before_result_publication': perf_counter() - started}
    force()
    atomic_json(folder / 'source_cost.json', result)
    return result
