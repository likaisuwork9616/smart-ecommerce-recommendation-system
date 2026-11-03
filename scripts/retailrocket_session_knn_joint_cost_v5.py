"""Target-blind joint structural roster and bounded V4 paired-cost summaries.

Selection never opens target/control/prediction files. A fresh private folder
contains all structural rows and the last-published frozen selection. The
external supervisor owns source/method binding, resource checks and deadline.
"""
from bisect import bisect_left
from collections import Counter
import hashlib
import heapq
import json
import math
import os
from pathlib import Path

from scripts import retailrocket_session_knn_cost_probe_v2 as base
from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json, encoded


POLICY = 'v5_joint_population_p90_four_directions_four_per_mask'
DIMENSIONS = ('eligible_neighbors', 'vote_memberships_upper', 'causal_candidates', 'variable_scalar_slots')
DIRECTIONS = {'all_four': DIMENSIONS, 'overlap_and_votes': DIMENSIONS[:2],
              'votes_and_payload': (DIMENSIONS[1], DIMENSIONS[3]),
              'catalog_and_payload': DIMENSIONS[2:]}
MASKS = tuple(f'{number:04b}' for number in range(16))
LIMITS = ['largest-500 membership sum bounds votes but does not select neighbors',
          'catalog denominator is exact; realized positive candidates and zero-fill work require ranking',
          'variable scalar slots cover history and selected neighbor lists only; they are not payload bytes',
          'finite targeted sample does not bound unsampled timing or actual joint vote/payload tails',
          'no full real query ledger, global fold, original bootstrap acceptance or full resume evidence']


def _cdf(histogram, count):
    """Integer empirical rank (# values <= v) and nearest-rank p90."""
    rank = {}
    p90 = None
    cumulative = 0
    for value in sorted(histogram):
        cumulative += histogram[value]
        rank[value] = cumulative
        if p90 is None and cumulative*10 >= 9*count:
            p90 = value
    if cumulative != count:
        raise ValueError('Incomplete structural dimension histogram')
    return rank, p90


def _shape_rows(db, source, config, support, catalog, watch):
    lo, hi = config['validation_window_ms']
    if type(lo) is not int or type(hi) is not int or hi <= lo:
        raise ValueError('Invalid validation window')
    first_times = sorted(catalog.values())
    db.execute('CREATE TEMP TABLE IF NOT EXISTS k1_v2_probe_history (i TEXT PRIMARY KEY) WITHOUT ROWID')
    previous = None
    ordinal = 0
    for raw in base.read_rows(Path(source)/'queries.csv', config['schemas']['queries.csv']):
        watch()
        if raw['role'] != 'validation':
            continue
        visitor = raw['visitorid']
        base.num(visitor)
        start, at, index = (base.num(raw[field]) for field in ('session_start_ms', 'query_ms', 'basket_index'))
        key = (visitor, start, at)
        if start > at or not lo <= at < hi or previous is not None and key <= previous:
            raise ValueError('Invalid clock, duplicate or unordered validation key')
        history = base._history(db, key, watch, index)
        work = base._work(db, history, key[:2], support, watch)
        slots = min(500, work['eligible_neighbors'])
        causal = bisect_left(first_times, at)
        # Each selected-neighbor row has 6 scalars: [v,s], a, b, [num,den].
        # Scores, targets, complete serialized bytes and positive votes are not used.
        yield dict(work, original_ordinal=ordinal, key=list(key), key_sha256=base._sha(list(key)),
                   time_band=4*(at-lo)//(hi-lo), history_sha256=base._sha(history), history_size=len(history),
                   selected_neighbor_slots=slots, variable_scalar_slots=len(history)+6*slots,
                   causal_candidates=causal, positive_candidates_upper=min(causal, work['vote_memberships_upper']))
        previous = key
        ordinal += 1


def _select(path, count, histograms, expected_digest, prior, watch):
    ranks, thresholds = {}, {}
    for name in DIMENSIONS:
        ranks[name], thresholds[name] = _cdf(histograms[name], count)
    cells = {mask: {'count': 0, 'heaps': {name: [] for name in DIRECTIONS}, 'maxima': {}} for mask in MASKS}
    prior_seen = set()
    digest = hashlib.sha256()
    scanned = 0
    with path.open('rb') as stream:
        for line in stream:
            watch()
            digest.update(line)
            row = json.loads(line)
            if row['original_ordinal'] != scanned:
                raise ValueError('Noncontiguous private structural roster')
            scanned += 1
            identity = row['key_sha256']
            if identity in prior:
                prior_seen.add(identity)
                for field in ('key', 'history_sha256', 'history_size', 'posting_work', 'eligible_neighbors',
                              'vote_memberships_upper', 'causal_candidates', 'current_session_excluded'):
                    if row[field] != prior[identity][field]:
                        raise ValueError('Prior probe structural identity differs: '+field)
            # A zero workload stays in the low class even if p90=0. Every tie
            # has the same class and the same integer percentile rank.
            mask = ''.join('1' if row[name] > 0 and row[name] >= thresholds[name] else '0' for name in DIMENSIONS)
            row['cell'] = mask
            bucket = cells[mask]
            bucket['count'] += 1
            for name in DIMENSIONS:
                bucket['maxima'][name] = max(bucket['maxima'].get(name, 0), row[name])
            for name, dimension_names in DIRECTIONS.items():
                values = [ranks[f][row[f]] if row[f] else 0 for f in dimension_names]
                # Maximize the weaker jointly present dimension, then their
                # sum. Smaller fixed key SHA wins ties, then original ordinal.
                quality = (min(values), sum(values), -int(identity, 16), -row['original_ordinal'])
                heap = bucket['heaps'][name]
                if len(heap) < 4:
                    heapq.heappush(heap, (quality, row))
                elif quality > heap[0][0]:
                    heapq.heapreplace(heap, (quality, row))
    if scanned != count or digest.hexdigest() != expected_digest or prior_seen != set(prior):
        raise ValueError('Incomplete or changed joint roster or missing prior probe')
    selected, public = [], {}
    for mask, bucket in cells.items():
        ordered = {name: [row for _, row in sorted(heap, key=lambda item: item[0], reverse=True)]
                   for name, heap in bucket['heaps'].items()}
        chosen = {}
        # Keep the best row from each fixed direction. If winners coincide,
        # use the next best from those same directions in the fixed order.
        for depth in range(4):
            for direction, candidates in ordered.items():
                if depth >= len(candidates):
                    continue
                candidate = candidates[depth]
                key = candidate['key_sha256']
                if key in chosen:
                    if depth == 0:
                        chosen[key]['selection_reasons'].append(direction)
                elif len(chosen) < 4:
                    chosen[key] = dict(candidate, selection_reasons=[direction if not depth else f'{direction}_rank_{depth+1}'])
        if len(chosen) != min(4, bucket['count']):
            raise ValueError('Incomplete frozen joint cell')
        selected.extend(chosen.values())
        public[mask] = {'population_queries': bucket['count'], 'selected_queries': len(chosen), 'maxima': bucket['maxima']}
    selected.sort(key=lambda row: row['original_ordinal'])
    return thresholds, public, selected


def freeze_joint_roster(folder, db, source, config, support, catalog, prior_probes, watch=lambda: None):
    """Write all structural rows and seal at most 4 probes per joint cell.

    Takes a connection to the sealed independent main database, with writable
    TEMP. prior_probes are the prior frozen metadata list (or [] on synthetic
    fixtures). Their identities are cross-checked only; selection ignores them.
    All key-bearing files and the returned probes must remain private.
    """
    directory = Path(folder)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory/'joint_roster.partial.jsonl'
    roster = directory/'joint_roster.jsonl'
    frozen = directory/'frozen_probes.json'
    if any(path.exists() for path in (temporary, roster, frozen)):
        raise FileExistsError('Joint roster requires a fresh namespace')
    expected = config['fixed_validation']['queries']
    if type(expected) is not int or expected < 1:
        raise ValueError('A positive fixed validation population is required')
    prior = {row['key_sha256']: row for row in prior_probes}
    if len(prior) != len(prior_probes) or len(prior) > 64 or any(base._sha(row['key']) != key for key, row in prior.items()):
        raise ValueError('Invalid prior frozen probe identities')
    histograms = {name: Counter() for name in DIMENSIONS}
    digest = hashlib.sha256()
    count = 0
    watch()
    with temporary.open('xb') as stream:
        for row in _shape_rows(db, source, config, support, catalog, watch):
            count += 1
            if count > expected:
                raise ValueError('Extra validation rows past fixed population')
            for name in DIMENSIONS:
                histograms[name][row[name]] += 1
            data = encoded(row)
            stream.write(data)
            digest.update(data)
        if count != expected:
            raise ValueError('Incomplete validation EOF while building joint roster')
        stream.flush()
        os.fsync(stream.fileno())
    thresholds, cells, probes = _select(temporary, count, histograms, digest.hexdigest(), prior, watch)
    population = {'selection_policy': POLICY, 'complete': True, 'expected_queries': expected, 'total_queries': count,
                  'selected_queries': len(probes), 'prior_probe_count': len(prior),
                  'prior_probe_overlap': sum(p['key_sha256'] in prior for p in probes),
                  'dimensions_in_mask_order': list(DIMENSIONS), 'p90_nearest_rank': thresholds,
                  'mask_rule': 'positive value at/above whole-population p90; zero always low; ties stay together',
                  'ranking': 'compare minimum then sum of empirical rank counts, then smallest key SHA; zero work has rank zero',
                  'joint_directions': {name: list(fields) for name, fields in DIRECTIONS.items()},
                  'cells': cells, 'roster_bytes': temporary.stat().st_size, 'roster_sha256': digest.hexdigest(),
                  'targets_used_for_selection': False, 'prediction_outputs_used_for_selection': False,
                  'full_query_predictions_for_selection': 0, 'formal_acceptance': False, 'T_plan': None,
                  'limitations': list(LIMITS)}
    result = {'population': population, 'probes': probes}
    watch()
    temporary.rename(roster)
    watch()
    atomic_json(frozen, result)
    return result


def summarize_joint_cost(frozen, measured, *, payload_bytes_by_ordinal=None):
    """Join completed V4 measurements to the frozen probes. Return only aggregates.

    Optional verified ledger frame byte lengths (with line terminator) must use
    original validation ordinals, not subset ordinals. Chunk commits are charged
    separately. No stratum maximum is a measured population runtime bound.
    """
    population, probes = frozen['population'], frozen['probes']
    if (population['selection_policy'] != POLICY or population['complete'] is not True or not 0 < len(probes) <= 64
            or len(probes) != measured['verified_subset_queries'] or measured['committed_prefix_rows'] != 0
            or len(measured['queries']) != len(probes)):
        raise ValueError('A complete fresh V4 verification of the frozen bounded subset is required')
    by_ordinal = {row['original_ordinal']: row for row in probes}
    if len(by_ordinal) != len(probes) or (payload_bytes_by_ordinal is not None and set(payload_bytes_by_ordinal) != set(by_ordinal)):
        raise ValueError('Duplicate or incomplete frozen payload ordinal roster')
    if payload_bytes_by_ordinal is not None and any(type(n) is not int or n <= 0 for n in payload_bytes_by_ordinal.values()):
        raise ValueError('Invalid verified payload frame length')
    if (set(population['cells']) != set(MASKS) or sum(c['population_queries'] for c in population['cells'].values()) != population['total_queries']
            or any(c['selected_queries'] != min(4, c['population_queries']) for c in population['cells'].values())):
        raise ValueError('Invalid frozen joint population coverage')
    cells = {mask: {'population_queries': cell['population_queries'], 'measured_queries': 0,
                    'max_query_seconds_excluding_commit': None, 'max_actual_work': {},
                    'sample_seconds_sum': {}, 'sample_seconds_max': {}, 'sample_rank_stage_seconds_sum': {}}
             for mask, cell in population['cells'].items()}
    seen = set()
    for subset, row in enumerate(measured['queries']):
        ordinal = row['original_ordinal']
        selected = by_ordinal.get(ordinal)
        if (selected is None or ordinal in seen or ordinal != probes[subset]['original_ordinal']
                or row['subset_ordinal'] != subset or row['key_sha256'] != selected['key_sha256']):
            raise ValueError('Measured original ordinal/key differs from frozen selection')
        seen.add(ordinal)
        work = row['sql_workload']
        for key, expected in [('history_rows_inserted', selected['history_size']),
                              ('sql_overlap_membership_matches', selected['posting_work']),
                              ('sql_overlap_groups_returned', selected['eligible_neighbors']+selected['current_session_excluded']),
                              ('sql_selected_rows_inserted', selected['selected_neighbor_slots']),
                              ('causal_catalog_candidates', selected['causal_candidates'])]:
            if work[key] != expected:
                raise ValueError('Actual measured structural work differs: '+key)
        votes = work['sql_vote_membership_rows_returned']
        if (not 0 <= work['positive_causal_candidates'] <= min(selected['positive_candidates_upper'], work['exact_vote_additions'])
                or not 0 <= work['exact_vote_additions'] <= votes <= selected['vote_memberships_upper']):
            raise ValueError('Actual vote/candidate work exceeds frozen structural bound')
        actual = {name: work[name] for name in ('sql_overlap_groups_returned', 'sql_vote_membership_rows_returned',
                  'exact_vote_additions', 'positive_causal_candidates', 'fallback_catalog_rows_examined',
                  'distinct_neighbor_similarities', 'vote_scale_bits')}
        if payload_bytes_by_ordinal is not None:
            actual['verified_payload_bytes'] = payload_bytes_by_ordinal[ordinal]
        bucket = cells[selected['cell']]
        bucket['measured_queries'] += 1
        for name, value in actual.items():
            bucket['max_actual_work'][name] = max(bucket['max_actual_work'].get(name, 0), value)
        for name in ('verification_seconds', 'rank_seconds', 'append_without_commit_seconds', 'chunk_commit_seconds'):
            value = row[name]
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid measured component time')
            bucket['sample_seconds_sum'][name] = bucket['sample_seconds_sum'].get(name, 0)+value
            bucket['sample_seconds_max'][name] = max(bucket['sample_seconds_max'].get(name, 0), value)
        for name, value in row['rank_stages_seconds'].items():
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid measured rank stage time')
            stages = bucket['sample_rank_stage_seconds_sum']
            stages[name] = stages.get(name, 0)+value
        query_time = row['verification_seconds']+row['append_without_commit_seconds']
        bucket['max_query_seconds_excluding_commit'] = max(bucket['max_query_seconds_excluding_commit'] or 0, query_time)
    for mask, cell in cells.items():
        if cell['measured_queries'] != population['cells'][mask]['selected_queries']:
            raise ValueError('Measured cell coverage differs')
    commits = measured['chunk_commits']
    if (not commits or any(c['completed'] is not True or type(c['records']) is not int or c['records'] < 1
                           or type(c['payload_bytes']) is not int or c['payload_bytes'] < 1
                           or type(c['seconds']) not in (float, int) or not math.isfinite(c['seconds']) or c['seconds'] < 0
                           for c in commits) or sum(c['records'] for c in commits) != len(probes)):
        raise ValueError('Incomplete measured checkpoint commits')
    if payload_bytes_by_ordinal is not None and sum(payload_bytes_by_ordinal.values()) != sum(c['payload_bytes'] for c in commits):
        raise ValueError('Verified physical ledger frame bytes differ from committed payload bytes')
    return {'kind': 'bounded_v4_joint_structural_tail_cost_only', 'selected_queries': len(probes),
            'population_queries': population['total_queries'], 'cells': cells,
            'conditional_query_component_seconds': sum(c['population_queries']*c['max_query_seconds_excluding_commit']
                  for c in cells.values() if c['measured_queries']),
            'projection': 'stratum population times sample maximum verify+append excluding chunk commit; engineering scenario only',
            'checkpoint_commits': len(commits), 'measured_chunk_commit_seconds': sum(c['seconds'] for c in commits),
            'measured_chunk_payload_bytes': sum(c['payload_bytes'] for c in commits),
            'verified_per_row_bytes_measured': payload_bytes_by_ordinal is not None,
            'formal_acceptance': False, 'full_readback_started': False, 'T_plan': None, 'reserved_test': 'locked',
            'limitations': list(LIMITS)}
