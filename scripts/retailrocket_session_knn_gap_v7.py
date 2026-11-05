"""Structural V7 selection, original-frame identity checks and subset costs."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell
from scripts.retailrocket_session_knn_sources_v4 import NAMES


PREFIX = b'k1-gap-v7-20261105\x00'


def _historical(probes):
    result = {}
    for row in probes:
        identity = row['key_sha256']
        if identity != _sha(row['key']) or identity in result:
            raise ValueError('Changed or duplicate historical query identity')
        result[identity] = row
    return result


def select_gap_roster(path, prior64, frozen48, specification, watch=lambda: None):
    """Read only the structural roster and select the two salted minima per gap."""
    rule = specification['selection']
    inventory = specification['actual_inventory']
    if rule['quota'] != 2 or rule['prefix_with_terminator'].encode('ascii') != PREFIX:
        raise ValueError('V7 salt and per-cell quota must match the frozen rule')
    history_a = _historical(prior64['probes'])
    history_b = _historical(frozen48['probes'])
    overlap = history_a.keys() & history_b.keys()
    for identity in overlap:
        if any(history_a[identity][field] != history_b[identity][field] for field in ('key', 'history_sha256')):
            raise ValueError('Historical rosters disagree on shared key')
    history = history_a | history_b
    if (len(overlap) != inventory['historical_64_and_48_intersection']
            or len(history) != inventory['distinct_historical_keys']):
        raise ValueError('Historical exclusion inventory changed')
    quotas = {row['cell']: row for row in specification['quotas']}
    if (len(quotas) != len(specification['quotas']) or not quotas
            or rule['planned_unique_queries'] != 2 * len(quotas)
            or not 1 <= rule['planned_unique_queries'] <= 64):
        raise ValueError('Invalid or duplicate fixed quota roster')
    best = {name: [] for name in quotas}
    population = frozen48['population']
    threshold = population['p90_nearest_rank']
    counts = Counter()
    excluded = Counter()
    old48_cells = set()
    seen = set()
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or identity != _sha(row['key']) or identity in seen
                    or any(type(row[name]) is not int or row[name] < 0 for name in DIMENSIONS)):
                raise ValueError('Invalid structural ordinal, identity or workload')
            seen.add(identity)
            parent = ''.join('1' if row[name] > 0 and row[name] >= threshold[name] else '0' for name in DIMENSIONS)
            cell = _cell(row, parent, 'neighbor_vote_grid')
            if identity in history_b:
                old48_cells.add(cell)
                if (history_b[identity]['original_ordinal'] != ordinal
                        or history_b[identity]['cell'] != parent):
                    raise ValueError('Frozen original probe ordinal or parent differs')
            if identity in history and any(history[identity][field] != row[field] for field in ('key', 'history_sha256')):
                raise ValueError('Historical identity differs from structural roster')
            if row['eligible_neighbors'] >= 100:
                continue
            counts[cell] += 1
            if identity in history:
                excluded[cell] += 1
                continue
            if cell in quotas:
                order = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
                bucket = best[cell]
                bucket.append((order, ordinal, dict(row, cell=cell)))
                bucket.sort(key=lambda item: item[:2])
                del bucket[2:]
    if (digest.hexdigest() != population['roster_sha256'] or len(seen) != inventory['population']
            or len(seen) != population['total_queries'] or not history.keys() <= seen):
        raise ValueError('Structural EOF, historical exclusions or roster SHA differs')
    if counts.keys() - old48_cells != quotas.keys():
        raise ValueError('Low-neighbor gap cell roster differs from the frozen quotas')
    chosen = []
    for cell, quota in quotas.items():
        if (quota['population'] != counts[cell] or quota['historical_exclusions'] != excluded[cell]
                or quota['eligible'] != counts[cell]-excluded[cell] or quota['planned_new_queries'] != 2
                or len(best[cell]) != 2):
            raise ValueError('Fixed quota or capacity shortfall; cannot redistribute')
        chosen.extend(item[2] for item in best[cell])
    return {'probes': sorted(chosen, key=lambda row: row['original_ordinal']),
            'roster_sha256': digest.hexdigest()}


def audit_gap_order(path, selection, prior64, frozen48, specification, watch=lambda: None):
    """Independently reproduce the two order statistics using a full sort."""
    exclusions = {row['key_sha256'] for group in (prior64, frozen48) for row in group['probes']}
    ranked = {row['cell']: [] for row in specification['quotas']}
    thresholds = frozen48['population']['p90_nearest_rank']
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            if row['eligible_neighbors'] > 99 or row['key_sha256'] in exclusions:
                continue
            mask = ''.join(str(int(row[d] != 0 and row[d] >= thresholds[d])) for d in DIMENSIONS)
            cell = _cell(row, mask, 'neighbor_vote_grid')
            if cell in ranked:
                salt = specification['selection']['prefix_with_terminator'].encode('ascii')
                token = hashlib.sha256(salt + bytes.fromhex(row['key_sha256'])).hexdigest()
                ranked[cell].append((token, ordinal, row['key_sha256']))
    expected = sorted((ordinal, key, cell) for cell, group in ranked.items()
                      for _, ordinal, key in sorted(group)[:2])
    actual = [(r['original_ordinal'], r['key_sha256'], r['cell']) for r in selection['probes']]
    if actual != expected or digest.hexdigest() != selection['roster_sha256']:
        raise ValueError('Independent full-sort selection or structural SHA differs')


def check_index(indexed, probes, expected_population, bound_sources, source_root):
    if (indexed['validation_queries'] != expected_population or indexed['sampled_queries'] != len(probes)
            or indexed['sampled_ordinals'] != [p['original_ordinal'] for p in probes]
            or set(indexed['sources']) != set(NAMES) or set(indexed['samples']) != set(NAMES)):
        raise ValueError('Seven-source extraction differs from the frozen ordinals')
    for source in indexed['sources'].values():
        path = (Path(indexed['source_root'])/source['path']).resolve().relative_to(source_root).as_posix()
        original = bound_sources.get(path)
        if original is None or (source['bytes'], source['sha256']) != (original['bytes'], original['sha256']):
            raise ValueError('Original source differs from its frozen binding')


def ledger_proof(store, probes):
    size = len(probes)
    recovered = store.recover()
    if (not 1 <= size <= 64 or recovered['records'] != size
            or store.get_stage('queries') != {'queries': size, 'paired_streams_eof_checked': True}
            or json.loads((store.folder/'stages/queries.json').read_bytes())['ledger'] != recovered
            or any((store.folder/name).exists() for name in ('candidate.json', 'acceptance.json'))):
        raise ValueError('Expected only a complete sealed engineering subset')
    digest = hashlib.sha256()
    count = total = 0
    for manifest in sorted((store.folder/'chunks').glob('*.json')):
        record = json.loads(manifest.read_bytes())
        with (store.folder/record['payload']['path']).open('rb') as stream:
            for line in stream:
                row = json.loads(line)
                if (count >= size or row['ordinal'] != count or row['key'] != probes[count]['key']
                        or row['payload']['expected']['key'] != row['key']):
                    raise ValueError('Committed ledger differs from frozen subset')
                digest.update(line)
                count += 1
                total += len(line)
    if count != size:
        raise ValueError('Incomplete physical ledger frames')
    return {'records': count, 'actual_committed_bytes': total, 'actual_committed_payload_sha256': digest.hexdigest(),
            'checkpoint_chain_checked': True}


def summarize_gap_cost(measured, detail, selection, specification):
    probes = selection['probes']
    quotas = {row['cell']: row for row in specification['quotas']}
    if (len(measured['queries']) != len(probes) or len(detail['rows']) != len(probes)
            or measured['verified_subset_queries'] != len(probes) or measured['committed_prefix_rows'] != 0):
        raise ValueError('A fresh complete gap subset is required')
    cells = {name: {'population': q['population'], 'measured': 0, 'seconds': {}, 'rank_stages_seconds': {},
                    'append_parts_seconds': {}, 'max_verify_append_excluding_direct_budget_seconds': 0.}
             for name, q in quotas.items()}
    for i, (probe, row, part, budget) in enumerate(zip(probes, measured['queries'], detail['rows'], detail['budget']['rows'])):
        if (row['subset_ordinal'] != i or part['subset_ordinal'] != i or budget['subset_ordinal'] != i
                or row['original_ordinal'] != probe['original_ordinal'] or row['key_sha256'] != probe['key_sha256']):
            raise ValueError('Measured identity differs from the sealed gap selection')
        work = row['sql_workload']
        if (work['sql_selected_rows_inserted'] != probe['eligible_neighbors']
                or work['sql_overlap_membership_matches'] != probe['posting_work']
                or work['causal_catalog_candidates'] != probe['causal_candidates']
                or work['sql_vote_membership_rows_returned'] > probe['vote_memberships_upper']):
            raise ValueError('Measured rank workload differs from the structural roster')
        cell = cells[probe['cell']]
        cell['measured'] += 1
        seconds = {k: row[k] for k in ('verification_seconds','rank_seconds','checkpoint_append_seconds',
                                        'append_without_commit_seconds','chunk_commit_seconds')}
        seconds['direct_budget_seconds'] = budget['query_append_budget_seconds']
        for target, source in [('seconds', seconds), ('rank_stages_seconds', row['rank_stages_seconds']),
                               ('append_parts_seconds', part['append_exclusive_seconds'])]:
            for key, value in source.items():
                cell[target][key] = cell[target].get(key, 0.) + value
        cost = row['verification_seconds'] + budget['append_without_commit_or_budget_seconds']
        cell['max_verify_append_excluding_direct_budget_seconds'] = max(
            cell['max_verify_append_excluding_direct_budget_seconds'], cost)
    if any(cell['measured'] != quotas[name]['planned_new_queries'] for name, cell in cells.items()):
        raise ValueError('Incomplete measured gap quotas')
    return {'cells': cells, 'setup_seconds': measured['setup_seconds'],
            'tail_flush_and_eof_seal_seconds': measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds': sum(c['seconds'] for c in measured['chunk_commits']),
            'budget_contexts': detail['budget']['by_context']}
