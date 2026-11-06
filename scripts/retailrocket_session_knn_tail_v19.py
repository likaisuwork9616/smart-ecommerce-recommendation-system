"""Frozen V19 tail reinforcement: per-segment extreme plus hash, old anchor, three repeats."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_gap_v7 import _historical
from scripts.retailrocket_session_knn_gap_v9 import _boundary
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell
from scripts.retailrocket_session_knn_cost_rollup_v17 import METRICS, _stats, normalize_repeat, summarize_costs
from scripts.retailrocket_session_knn_reinforcement_v18 import (
    HISTORY as BASE_HISTORY, _history as _base_history, _selection_counts as _v18_selection_counts,
    TelemetrySampler, summarize_telemetry)


CELL = '1101/n5/v4'
CELLS = (CELL,)
SEGMENTS = {'n1946_2499': (1946, 2499), 'n2500_2999': (2500, 2999), 'n3000_4999': (3000, 4999)}
PREFIX = b'k1-tail-v19-20261106\x00'
HISTORY = (*BASE_HISTORY, 'V18')


def validate_spec(spec):
    """Validate the sealed design without selecting real queries or running rankings."""
    selection, measurement, telemetry = (spec[k] for k in ('selection', 'measurement', 'telemetry'))
    rows = spec['quotas']
    quotas = {row['segment']: row for row in rows}
    population = spec['target_population']
    if (spec['target_cell'] != CELL or len(rows) != 3 or set(quotas) != set(SEGMENTS)
            or selection['quota_by_segment'] != dict.fromkeys(SEGMENTS, 2)
            or (selection['planned_new_queries'], selection['planned_anchor_queries'], selection['planned_unique_queries']) != (6, 1, 7)
            or selection['prefix_with_terminator'].encode('ascii') != PREFIX
            or selection['strategy'] != 'segment_max_then_hash'
            or (measurement['fresh_repeats'], measurement['queries_per_repeat'], measurement['expected_engineering_checks']) != (3, 7, 21)
            or telemetry['interval_seconds'] != .2 or telemetry['process_name_prefix'] != 'ollama'
            or any(type(population[k]) is not int or population[k] < 0 for k in (
                'population', 'historical_exclusions', 'eligible', 'existing_comparable_queries'))
            or population['population'] != population['historical_exclusions'] + population['eligible']
            or population['existing_comparable_queries'] != 5):
        raise ValueError('V19 requires three fixed extreme-plus-hash pairs and one old anchor, repeated three times')
    for name, row in quotas.items():
        if (any(type(row[k]) is not int or row[k] < 0 for k in (
                'lower_inclusive', 'upper_inclusive', 'population', 'historical_exclusions', 'eligible', 'planned_new_queries'))
                or (row['lower_inclusive'], row['upper_inclusive']) != SEGMENTS[name]
                or row['planned_new_queries'] != 2 or row['eligible'] < 2
                or row['population'] != row['historical_exclusions'] + row['eligible']):
            raise ValueError('Tail boundaries, capacities and two-query quotas are immutable; no quota transfers')
    if any(sum(row[k] for row in rows) > population[k] for k in ('population', 'historical_exclusions', 'eligible')):
        raise ValueError('Tail capacities exceed the whole-cell inventory')
    if 'target_tail' in spec:
        tail = spec['target_tail']
        if (tail['lower_exclusive'] != 1945 or tail['existing_comparable_queries'] != 0
                or any(type(tail[k]) is not int or tail[k] != sum(row[k] for row in rows)
                       for k in ('population', 'historical_exclusions', 'eligible'))):
            raise ValueError('Registered tail totals differ from the three segments')
    return quotas


def _history(histories):
    if set(histories) != set(HISTORY):
        raise ValueError('V19 requires all thirteen frozen historical cohorts including V18')
    history, masks, fine = _base_history({name: histories[name] for name in BASE_HISTORY})
    recent = histories['V18']
    _v18_selection_counts(recent['probes'])
    if (recent['new_keys'], recent['anchor_keys']) != (8, 2):
        raise ValueError('V18 must retain its eight new queries and two reused anchors')
    prior = set(history)
    added = _historical(recent['probes'])
    anchors = {row['key_sha256'] for row in recent['probes'] if row['sample_role'] == 'anchor'}
    new = {row['key_sha256'] for row in recent['probes'] if row['sample_role'] == 'new'}
    old48 = {row['key_sha256'] for row in histories['V6']['probes']}
    if (set(added) & prior != anchors or not anchors <= old48 or new & prior
            or len(anchors) != 2 or len(new) != 8 or len(prior | set(added)) != 226
            or recent['roster_sha256'] != histories['V6']['population']['roster_sha256']):
        raise ValueError('V18 overlap must be exactly its two V6 anchors, yielding 226 historical identities')
    for identity in anchors:
        if any(added[identity][k] != history[identity][k] for k in ('key', 'history_sha256', 'original_ordinal')):
            raise ValueError('V18 anchor identity or ordinal differs from its earlier scientific query')
    history.update({identity: added[identity] for identity in new})
    fine.update(added)
    return history, masks, fine


def _segment(neighbors):
    for name, (lower, upper) in SEGMENTS.items():
        if lower <= neighbors <= upper:
            return name
    return None


def _tag(row, segment, reason):
    return dict(row, cell=CELL, sample_role='anchor' if reason == 'anchor' else 'new',
                selection_segment=segment, selection_reason=reason)


def _anchor_id(histories):
    anchors = [row['key_sha256'] for row in histories['V18']['probes']
               if row['cell'] == CELL and row['sample_role'] == 'anchor']
    if len(anchors) != 1:
        raise ValueError('The unique V6 n5 anchor retained in V18 must be reused')
    return anchors[0]


def select_tail_roster(path, histories, spec, watch=lambda: None):
    quotas = validate_spec(spec)
    history, masks, fine = _history(histories)
    population = histories['V6']['population']
    anchor_id = _anchor_id(histories)
    old48 = {row['key_sha256'] for row in histories['V6']['probes']}
    seen, counts, excluded = set(), Counter(), Counter()
    whole_count = whole_excluded = 0
    maxima, hashes, anchors = {}, {name: [] for name in SEGMENTS}, []
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or _sha(row['key']) != identity or identity in seen
                    or any(type(row[k]) is not int or row[k] < 0 for k in DIMENSIONS)):
                raise ValueError('Invalid structural roster identity, ordinal or workload')
            seen.add(identity)
            parent = ''.join('1' if row[k] > 0 and row[k] >= population['p90_nearest_rank'][k] else '0' for k in DIMENSIONS)
            cell = _cell(row, parent, 'neighbor_vote_grid')
            if identity in history:
                if any(history[identity][k] != row[k] for k in ('key', 'history_sha256')):
                    raise ValueError('Historical identity differs from the roster')
                for group, label in ((masks, parent), (fine, cell)):
                    if identity in group and (group[identity]['original_ordinal'], group[identity]['cell']) != (ordinal, label):
                        raise ValueError('Historical ordinal or stratum changed')
            if cell != CELL:
                continue
            whole_count += 1
            if identity in history:
                whole_excluded += 1
                if identity in old48:
                    anchors.append(_tag(row, 'anchor', 'anchor'))
            segment = _segment(row['eligible_neighbors'])
            if segment is None:
                continue
            counts[segment] += 1
            if identity in history:
                excluded[segment] += 1
                continue
            token = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
            extreme = (-row['eligible_neighbors'], token, ordinal, row)
            if segment not in maxima or extreme[:3] < maxima[segment][:3]:
                maxima[segment] = extreme
            hashes[segment].append((token, ordinal, row))
            hashes[segment].sort(key=lambda value: value[:2])
            del hashes[segment][2:]
        length = stream.tell()
    if (len(seen) != population['total_queries'] or length != population['roster_bytes']
            or digest.hexdigest() != population['roster_sha256'] or not history.keys() <= seen):
        raise ValueError('Incomplete or changed structural source')
    target = spec['target_population']
    if ((whole_count, whole_excluded, whole_count-whole_excluded) != tuple(target[k] for k in (
            'population', 'historical_exclusions', 'eligible'))
            or len(anchors) != 1 or anchors[0]['key_sha256'] != anchor_id):
        raise ValueError('Whole-cell inventory or the original V6/V18 n5 anchor differs')
    chosen = list(anchors)
    for name, quota in quotas.items():
        if (counts[name], excluded[name], counts[name]-excluded[name], len(hashes[name])) != (
                quota['population'], quota['historical_exclusions'], quota['eligible'], 2):
            raise ValueError('Tail population, exclusions or eligible quota differs')
        maximum = maxima[name][3]
        second = next(row for _, _, row in hashes[name] if row['key_sha256'] != maximum['key_sha256'])
        chosen.extend((_tag(maximum, name, 'segment_max'), _tag(second, name, 'hash')))
    selection = {'probes': sorted(chosen, key=lambda row: row['original_ordinal']),
                 'roster_sha256': digest.hexdigest(), 'new_keys': 6, 'anchor_keys': 1}
    _selection_counts(selection['probes'], spec)
    return selection


def audit_tail_order(path, selection, histories, spec, watch=lambda: None):
    """Independently classify literal boundaries and fully order each eligible segment."""
    quotas = validate_spec(spec)
    excluded = {row['key_sha256'] for name in HISTORY for row in histories[name]['probes']}
    old48 = {row['key_sha256'] for row in histories['V6']['probes']}
    anchor_id = _anchor_id(histories)
    population = histories['V6']['population']
    candidates, anchors = {name: [] for name in SEGMENTS}, []
    counts, exclusions = Counter(), Counter()
    whole_count = whole_excluded = 0
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            parent = ''.join(str(int(0 < row[k] and population['p90_nearest_rank'][k] <= row[k])) for k in DIMENSIONS)
            neighbors, upper = row['eligible_neighbors'], row['vote_memberships_upper']
            if parent != '1101' or not 1000 <= neighbors <= 4999 or not 2000 <= upper <= 9999:
                continue
            whole_count += 1
            identity = row['key_sha256']
            if identity in excluded:
                whole_excluded += 1
                if identity in old48:
                    anchors.append(dict(row, cell=CELL, sample_role='anchor', selection_segment='anchor', selection_reason='anchor'))
            if 1946 <= neighbors <= 2499:
                segment = 'n1946_2499'
            elif 2500 <= neighbors <= 2999:
                segment = 'n2500_2999'
            elif 3000 <= neighbors <= 4999:
                segment = 'n3000_4999'
            else:
                continue
            counts[segment] += 1
            if identity in excluded:
                exclusions[segment] += 1
                continue
            token = hashlib.sha256(spec['selection']['prefix_with_terminator'].encode('ascii') + bytes.fromhex(identity)).hexdigest()
            candidates[segment].append((neighbors, token, ordinal, row))
    target = spec['target_population']
    if ((whole_count, whole_excluded, whole_count-whole_excluded) != tuple(target[k] for k in (
            'population', 'historical_exclusions', 'eligible'))
            or len(anchors) != 1 or anchors[0]['key_sha256'] != anchor_id):
        raise ValueError('Independent whole-cell inventory or anchor differs')
    wanted = list(anchors)
    for name, quota in quotas.items():
        values = candidates[name]
        if (counts[name], exclusions[name], len(values)) != (
                quota['population'], quota['historical_exclusions'], quota['eligible']):
            raise ValueError('Independent tail eligibility differs')
        extreme = sorted(values, key=lambda value: (-value[0], value[1], value[2]))[0]
        remaining = [value for value in values if value[2] != extreme[2]]
        hashed = sorted(remaining, key=lambda value: (value[1], value[2]))[0]
        for value, reason in ((extreme, 'segment_max'), (hashed, 'hash')):
            wanted.append(dict(value[3], cell=CELL, sample_role='new', selection_segment=name, selection_reason=reason))
    expected = {'probes': sorted(wanted, key=lambda row: row['original_ordinal']),
                'roster_sha256': digest.hexdigest(), 'new_keys': 6, 'anchor_keys': 1}
    if expected != selection or digest.hexdigest() != population['roster_sha256']:
        raise ValueError('Independent V19 full sorting, maximum selection or original anchor differs')


def _selection_counts(probes, spec):
    validate_spec(spec)
    required = Counter({(name, reason): 1 for name in SEGMENTS for reason in ('segment_max', 'hash')})
    required['anchor', 'anchor'] = 1
    counts = Counter((p['selection_segment'], p['selection_reason']) for p in probes)
    if (len(probes) != 7 or len({p['key_sha256'] for p in probes}) != 7
            or [p['original_ordinal'] for p in probes] != sorted({p['original_ordinal'] for p in probes})
            or counts != required or any(p['cell'] != CELL for p in probes)):
        raise ValueError('Expected seven ordered identities: maximum plus hash per segment and one old anchor')
    for row in probes:
        anchor = row['selection_reason'] == 'anchor'
        if (row['sample_role'] != ('anchor' if anchor else 'new')
                or not 1000 <= row['eligible_neighbors'] <= 4999
                or not 2000 <= row['vote_memberships_upper'] <= 9999
                or not anchor and _segment(row['eligible_neighbors']) != row['selection_segment']):
            raise ValueError('Selected role, tail segment or original n5/v4 stratum differs')


def _workload_group(rows):
    n = [p['eligible_neighbors'] for p, _, _ in rows]
    bounds = [p['vote_memberships_upper'] for p, _, _ in rows]
    sums = {k: sum(work[k] for _, work, _ in rows) for k in (
        'neighbor_pool_rows_hashed', 'sql_selected_rows_inserted', 'sql_vote_membership_rows_returned', 'exact_vote_additions')}
    ties, excluded = sum(b[1] for _, _, b in rows), sum(b[2] for _, _, b in rows)
    return dict(sums, queries=len(rows), new_queries=sum(p['sample_role'] == 'new' for p, _, _ in rows),
                anchor_queries=sum(p['sample_role'] == 'anchor' for p, _, _ in rows),
                eligible_neighbors_min=min(n), eligible_neighbors_max=max(n),
                vote_upper_min=min(bounds), vote_upper_max=max(bounds), vote_upper_sum=sum(bounds),
                vote_upper_slack=sum(bounds)-sums['sql_vote_membership_rows_returned'],
                under500_queries=0, exact500_queries=0, over500_queries=len(rows),
                boundary_queries=sum(b[0] for _, _, b in rows), boundary_ties_total=ties,
                boundary_ties_selected=ties-excluded, boundary_ties_excluded=excluded)


def sample_workload(probes, measured, predictions, spec):
    _selection_counts(probes, spec)
    rows = []
    for probe, row, prediction in zip(probes, measured['queries'], predictions, strict=True):
        n, upper = probe['eligible_neighbors'], probe['vote_memberships_upper']
        work = row['sql_workload']
        votes = work['sql_vote_membership_rows_returned']
        if (not 500 <= votes <= upper
                or (row['original_ordinal'], row['key_sha256']) != (probe['original_ordinal'], probe['key_sha256'])
                or work['neighbor_pool_rows_hashed'] != n or work['sql_selected_rows_inserted'] != 500
                or work['sql_overlap_membership_matches'] != probe['posting_work']
                or work['causal_catalog_candidates'] != probe['causal_candidates']
                or not 0 <= work['exact_vote_additions'] <= votes):
            raise ValueError('Frozen V19 full pool, capped workload or structural counts differ')
        rows.append((probe, work, _boundary(probe, work, prediction)))
    result = _workload_group(rows)
    result['by_segment'] = {name: _workload_group([r for r in rows if r[0]['selection_segment'] == name]) for name in SEGMENTS}
    result['by_role'] = {role: _workload_group([r for r in rows if r[0]['sample_role'] == role]) for role in ('new', 'anchor')}
    return {CELL: result}


def compare_repeats(folder, repeats, spec):
    validate_spec(spec)
    count_required = spec['measurement']['queries_per_repeat']
    if len(repeats) != 3 or any(repeat['proof']['records'] != count_required for repeat in repeats):
        raise ValueError('Exactly three complete seven-query repeats are required')
    if any(repeat['proof'] != repeats[0]['proof'] or repeat['workload_by_cell'] != repeats[0]['workload_by_cell'] for repeat in repeats[1:]):
        raise ValueError('The three saved proofs or logical workloads differ')
    def frames(index):
        root = Path(folder)/f'repeat_{index}'/'verified_subset'
        for manifest in sorted((root/'chunks').glob('*.json')):
            payload = json.loads(manifest.read_bytes())['payload']['path']
            path = (root/payload).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError('Physical ledger path escapes the checkpoint')
            with path.open('rb') as stream:
                yield from stream
    count = total = 0
    digest = hashlib.sha256()
    for row0, row1, row2 in zip(*(frames(i) for i in range(3)), strict=True):
        if row0 != row1 or row0 != row2:
            raise ValueError('Corresponding physical frames differ across the three repeats')
        digest.update(row0)
        total += len(row0)
        count += 1
    proof = repeats[0]['proof']
    if (count, total, digest.hexdigest()) != (count_required, proof['actual_committed_bytes'], proof['actual_committed_payload_sha256']):
        raise ValueError('Physical frame count, bytes or concatenated digest differs')


def _describe_repeat_profiles(result, rows):
    """Retain observed per-identity repeat extrema without projecting population costs."""
    result.pop('scenario_inputs_seconds')
    by_key = defaultdict(list)
    for row in rows:
        by_key[row['key_sha256']].append(row)
    for metric in METRICS:
        values = [[row['seconds'][metric] for row in group] for group in by_key.values()]
        result['within_query_temporal'][metric]['query_repeat_minimum_seconds'] = _stats(min(v) for v in values)
        result['within_query_temporal'][metric]['query_repeat_maximum_seconds'] = _stats(max(v) for v in values)
    return result


def _descriptive_cell(rows, population):
    size = len({row['key_sha256'] for row in rows})
    result = summarize_costs({CELL: population}, rows, [], {'V19': {'queries': size, 'repeats': 3}})['cells'][CELL]
    return _describe_repeat_profiles(result, rows)


def summarize_repeats(selection, repeats, spec):
    quotas = validate_spec(spec)
    probes = selection['probes']
    _selection_counts(probes, spec)
    if len(repeats) != 3 or (selection['new_keys'], selection['anchor_keys']) != (6, 1):
        raise ValueError('V19 requires all three retained repeats and unchanged sample roles')
    metadata = {p['key_sha256']: p for p in probes}
    normalized = [normalize_repeat('V19', i, probes, repeat['measured'], repeat['observations'], dict.fromkeys(metadata, CELL))
                  for i, repeat in enumerate(repeats)]
    rows = [row for repeat in normalized for row in repeat['rows']]
    result = summarize_costs({CELL: spec['target_population']['population']}, rows,
        [repeat['overheads'] for repeat in normalized], {'V19': {'queries': 7, 'repeats': 3}})
    # The deliberate extreme-plus-hash design is not an equal-probability sample.
    # Population-weighted projections and their inputs are intentionally withheld.
    result.pop('weighted_scenarios_seconds')
    summary = result['cells'][CELL]
    _describe_repeat_profiles(summary, rows)
    summary['new_queries'], summary['anchor_queries'] = 6, 1
    summary['roles'], summary['segments'], summary['selection_reasons'] = {}, {}, {}
    for role in ('new', 'anchor'):
        subset = [r for r in rows if metadata[r['key_sha256']]['sample_role'] == role]
        item = _descriptive_cell(subset, spec['target_population']['population'])
        item.pop('population_queries')
        summary['roles'][role] = item
    for name, quota in quotas.items():
        subset = [r for r in rows if metadata[r['key_sha256']]['selection_segment'] == name]
        summary['segments'][name] = _descriptive_cell(subset, quota['population'])
    for reason in ('segment_max', 'hash'):
        subset = [r for r in rows if metadata[r['key_sha256']]['selection_reason'] == reason]
        item = _descriptive_cell(subset, spec['target_population']['population'])
        item.pop('population_queries')
        summary['selection_reasons'][reason] = item
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['key_sha256']].append(row)
    largest = None
    for identity, observations in grouped.items():
        fastest = min(observations, key=lambda r: (r['seconds']['core'], r['repeat_index']))
        slowest = max(observations, key=lambda r: (r['seconds']['core'], -r['repeat_index']))
        delta = {metric: slowest['seconds'][metric]-fastest['seconds'][metric] for metric in METRICS}
        item = {k: metadata[identity][k] for k in ('sample_role', 'selection_segment', 'selection_reason')}
        item.update(fast_repeat=fastest['repeat_index'], slow_repeat=slowest['repeat_index'],
                    fast_core_seconds=fastest['seconds']['core'], slow_core_seconds=slowest['seconds']['core'], delta_seconds=delta)
        if largest is None or delta['core'] > largest['delta_seconds']['core']:
            largest = item
    summary['max_same_query_range_decomposition'] = largest
    result['scope'].update(new_keys=6, anchor_keys=1, engineering_checks=21,
                          distinct_historically_verified_queries=232, distinct_comparable_queries=170,
                          target_cell_distinct_queries={CELL: 11}, target_tail_distinct_queries=6,
                          globally_covered_cells=55, globally_uncovered_cells=0)
    result['interpretation']['weighting'] = 'No population-weighted scenario is published. Each segment deliberately selects its eligible maximum and one remaining hash-selected query; these samples and the reused anchor are not a uniform sample of the cell or its tail.'
    result['interpretation']['accounting'] = 'Rank contains vote SQL and is nested in verification. Core is same-row verification plus append excluding nested commit and direct budget writes. Component medians must not be added. Setup, tail, all chunk commits and budget totals are separate overlapping diagnostics, not extra disjoint costs.'
    result['interpretation']['limits'] = 'Seven fixed identities in one engineering window provide no confidence interval, causal speedup, future latency guarantee or full-run runtime bound. Telemetry describes each whole repeat, not per-query or process-specific causation.'
    result['interpretation']['tail_reinforcement'] = 'Six new tail queries and one unchanged V6/V18 anchor are separated by role, segment and selection reason. All three repeats are retained; prior anchor windows are descriptive temporal comparisons only.'
    return result
