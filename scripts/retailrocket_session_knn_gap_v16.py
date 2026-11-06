"""Select and verify all remaining V16 uncapped n3 and capped n5 probes."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_gap_v7 import _historical
from scripts.retailrocket_session_knn_gap_v8 import compare_frames
from scripts.retailrocket_session_knn_gap_v9 import _boundary
from scripts.retailrocket_session_knn_gap_v10 import _all_history
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell


CELLS = ('0001/n3/v3', '0001/n3/v4', '1011/n5/v4')
QUOTA_BY_CELL = dict(zip(CELLS, (4, 4, 2), strict=True))
PREFIX = b'k1-gap-v16-20261106\x00'


def _quotas(specification):
    rule = specification['selection']
    rows = specification['quotas']
    quotas = {row['cell']: row for row in rows}
    if (len(rows) != 3 or set(quotas) != set(CELLS) or 'quota' in rule
            or rule['quota_by_cell'] != QUOTA_BY_CELL
            or (rule['planned_unique_queries'], rule['prefix_with_terminator'].encode('ascii')) != (10, PREFIX)
            or any(type(row[field]) is not int or row[field] < 0 for row in rows
                   for field in ('population', 'historical_exclusions', 'eligible', 'planned_new_queries'))
            or any(row['planned_new_queries'] != QUOTA_BY_CELL[row['cell']]
                   or row['eligible'] != row['planned_new_queries']
                   or row['population'] != row['historical_exclusions'] + row['eligible'] for row in rows)):
        raise ValueError('V16 requires the three frozen cells, salt and complete eligible quotas of 4/4/2')
    return quotas


def select_gap_roster(path, prior64, frozen48, prior34, prior8_v8, prior8_v9, prior8_v10, prior8_v11, prior8_v12, prior8_v13, prior8_v14, prior8_v15,
                      specification, watch=lambda: None):
    """Verify the full roster while retaining each cell's frozen quota in hash order."""
    quotas = _quotas(specification)
    history, mask_history, fine_history = _all_history(prior64, frozen48, prior34, prior8_v8, prior8_v9)
    for cohort in (prior8_v10, prior8_v11, prior8_v12, prior8_v13, prior8_v14, prior8_v15):
        recent = _historical(cohort['probes'])
        if recent.keys() & history.keys():
            raise ValueError('Recent historical cohort overlaps an earlier cohort')
        history.update(recent)
        fine_history.update(recent)

    population = frozen48['population']
    thresholds = population['p90_nearest_rank']
    seen, counts, exclusions = set(), Counter(), Counter()
    best = {cell: [] for cell in quotas}
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or _sha(row['key']) != identity or identity in seen
                    or any(type(row[field]) is not int or row[field] < 0 for field in DIMENSIONS)):
                raise ValueError('Invalid structural identity, ordinal or workload')
            seen.add(identity)
            mask = ''.join('1' if row[k] > 0 and row[k] >= thresholds[k] else '0' for k in DIMENSIONS)
            cell = _cell(row, mask, 'neighbor_vote_grid')
            if identity in history:
                if any(history[identity][k] != row[k] for k in ('key', 'history_sha256')):
                    raise ValueError('Historic identity differs from structural roster')
                for group, label in ((mask_history, mask), (fine_history, cell)):
                    if identity in group:
                        old = group[identity]
                        if (old['original_ordinal'], old['cell']) != (ordinal, label):
                            raise ValueError('Historic ordinal or stratum differs')
                        if cell in quotas:
                            raise ValueError('Requested cell already has a comparable probe')
            if cell not in quotas:
                continue
            counts[cell] += 1
            if identity in history:
                exclusions[cell] += 1
                continue
            token = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
            best[cell].append((token, ordinal, dict(row, cell=cell)))
            best[cell].sort(key=lambda candidate: candidate[:2])
            del best[cell][quotas[cell]['planned_new_queries']:]
        length = stream.tell()
    if (length != population['roster_bytes'] or digest.hexdigest() != population['roster_sha256']
            or len(seen) != population['total_queries'] or not history.keys() <= seen):
        raise ValueError('Incomplete structural roster or historical identities')
    probes = []
    for cell, quota in quotas.items():
        if (counts[cell], exclusions[cell], counts[cell] - exclusions[cell], len(best[cell])) != (
                quota['population'], quota['historical_exclusions'], quota['eligible'], quota['planned_new_queries']):
            raise ValueError('Frozen cell capacity, exclusions or quota differ')
        probes.extend(row for _, _, row in best[cell])
    return {'probes': sorted(probes, key=lambda row: row['original_ordinal']), 'roster_sha256': digest.hexdigest()}


def audit_gap_order(path, selection, prior64, frozen48, prior34, prior8_v8, prior8_v9, prior8_v10, prior8_v11, prior8_v12, prior8_v13, prior8_v14, prior8_v15,
                    specification, watch=lambda: None):
    """Independently classify by literal bands, hash every eligible key and fully sort all three cells."""
    quotas = _quotas(specification)
    cohorts = (prior64, frozen48, prior34, prior8_v8, prior8_v9, prior8_v10, prior8_v11, prior8_v12, prior8_v13, prior8_v14, prior8_v15)
    excluded = {row['key_sha256'] for cohort in cohorts for row in cohort['probes']}
    thresholds = frozen48['population']['p90_nearest_rank']
    salt = specification['selection']['prefix_with_terminator'].encode('ascii')
    candidates = {cell: [] for cell in quotas}
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if identity in excluded:
                continue
            neighbors = row['eligible_neighbors']
            upper = row['vote_memberships_upper']
            mask = ''.join(str(int(0 < row[k] and thresholds[k] <= row[k])) for k in DIMENSIONS)
            if mask == '0001' and 100 <= neighbors <= 499 and 500 <= upper <= 1999:
                cell = CELLS[0]
            elif mask == '0001' and 100 <= neighbors <= 499 and 2000 <= upper <= 9999:
                cell = CELLS[1]
            elif mask == '1011' and 1000 <= neighbors <= 4999 and 2000 <= upper <= 9999:
                cell = CELLS[2]
            else:
                continue
            order = hashlib.sha256(salt + bytes.fromhex(identity)).hexdigest()
            candidates[cell].append((order, ordinal, dict(row, cell=cell)))
    winners = []
    for cell, values in candidates.items():
        if len(values) != quotas[cell]['eligible']:
            raise ValueError('Independent sort found a different number of eligible queries')
        winners.extend(row for _, _, row in sorted(values, key=lambda item: item[:2])[:quotas[cell]['planned_new_queries']])
    winners.sort(key=lambda row: row['original_ordinal'])
    if (len(winners) != specification['selection']['planned_unique_queries'] or winners != selection['probes']
            or digest.hexdigest() != selection['roster_sha256']
            or digest.hexdigest() != frozen48['population']['roster_sha256']):
        raise ValueError('Independent V16 sort or source digest differs')


def check_coverage(remaining, added_cells, total_cells=55, historic_unique=208, new_keys=10):
    if (set(added_cells) != set(CELLS) or remaining != QUOTA_BY_CELL
            or (total_cells, historic_unique, new_keys) != (55, 208, 10)
            or any(data['population'] != remaining[cell] or data['measured'] != QUOTA_BY_CELL[cell]
                   for cell, data in added_cells.items())):
        raise ValueError('Coverage requires all remaining 4/4/2 queries and the frozen 208-query history')
    missing = {cell: count for cell, count in remaining.items() if cell not in added_cells}
    return {
        'v6_plus_new_cells_with_sample': total_cells - len(missing),
        'uncovered_cells': len(missing),
        'v6_plus_new_unrepresented_population': sum(missing.values()),
        'distinct_historically_verified_queries': historic_unique + new_keys,
    }, missing


def _work(probe, measured):
    neighbors = probe['eligible_neighbors']
    upper = probe['vote_memberships_upper']
    cap = min(neighbors, 500)
    work = measured['sql_workload']
    votes = work['sql_vote_membership_rows_returned']
    if probe['cell'] == CELLS[0]:
        valid = 100 <= neighbors <= 499 and 500 <= upper <= 1999 and votes == upper
    elif probe['cell'] == CELLS[1]:
        valid = 100 <= neighbors <= 499 and 2000 <= upper <= 9999 and votes == upper
    else:
        valid = probe['cell'] == CELLS[2] and 1000 <= neighbors <= 4999 and 2000 <= upper <= 9999 and cap <= votes <= upper
    if (not valid
            or (probe['original_ordinal'], probe['key_sha256']) != (measured['original_ordinal'], measured['key_sha256'])
            or work['neighbor_pool_rows_hashed'] != neighbors or work['sql_selected_rows_inserted'] != cap
            or not 0 <= work['exact_vote_additions'] <= votes):
        raise ValueError('Frozen query, eligible pool, selected neighbors, votes or causal additions differ')
    return work


def sample_workload(probes, measured, predictions):
    groups = {cell: [] for cell in CELLS}
    for probe, row, prediction in zip(probes, measured['queries'], predictions, strict=True):
        work = _work(probe, row)
        # V4 checks SQL vote counts against each selected size before the four-arm frame comparison.
        # The boundary check also reconstructs the pool digest when every neighbor is selected.
        boundary = _boundary(probe, work, prediction)
        groups[probe['cell']].append((probe, work, boundary))
    result = {}
    for cell, rows in groups.items():
        if len(rows) != QUOTA_BY_CELL[cell]:
            raise ValueError('Each cell requires its frozen number of measured queries')
        neighbors = [probe['eligible_neighbors'] for probe, _, _ in rows]
        bounds = [probe['vote_memberships_upper'] for probe, _, _ in rows]
        totals = {k: sum(work[k] for _, work, _ in rows) for k in (
            'sql_selected_rows_inserted', 'neighbor_pool_rows_hashed', 'sql_vote_membership_rows_returned',
            'exact_vote_additions')}
        ties = sum(boundary[1] for _, _, boundary in rows)
        removed = sum(boundary[2] for _, _, boundary in rows)
        result[cell] = dict(totals, eligible_neighbors_min=min(neighbors), eligible_neighbors_max=max(neighbors),
                            vote_upper_min=min(bounds), vote_upper_max=max(bounds), vote_upper_sum=sum(bounds),
                            vote_upper_slack=sum(bounds) - totals['sql_vote_membership_rows_returned'],
                            under500_queries=sum(n < 500 for n in neighbors), exact500_queries=neighbors.count(500),
                            over500_queries=sum(n > 500 for n in neighbors),
                            boundary_queries=sum(boundary[0] for _, _, boundary in rows), boundary_ties_total=ties,
                            boundary_ties_selected=ties - removed, boundary_ties_excluded=removed)
    return result


def summarize_gap_cost(measured, detail, selection, specification):
    probes = selection['probes']
    quotas = _quotas(specification)
    cells = {cell: {'population': q['population'], 'measured': 0, 'seconds': {}, 'rank_stages_seconds': {},
                    'append_parts_seconds': {}, 'max_verify_append_excluding_direct_budget_seconds': 0.}
             for cell, q in quotas.items()}
    planned = specification['selection']['planned_unique_queries']
    if len(probes) != planned or measured['verified_subset_queries'] != planned or measured['committed_prefix_rows'] != 0:
        raise ValueError('A fresh ten-query repeat is required')
    rows = zip(probes, measured['queries'], detail['rows'], detail['budget']['rows'], strict=True)
    for ordinal, (probe, row, part, budget) in enumerate(rows):
        work = _work(probe, row)
        if (any(record['subset_ordinal'] != ordinal for record in (row, part, budget))
                or work['sql_overlap_membership_matches'] != probe['posting_work']
                or work['causal_catalog_candidates'] != probe['causal_candidates']):
            raise ValueError('Structural scan or timing row ordinal differs from frozen query')
        cell = cells[probe['cell']]
        cell['measured'] += 1
        seconds = {name: row[name] for name in ('verification_seconds', 'rank_seconds', 'checkpoint_append_seconds',
                                                'append_without_commit_seconds', 'chunk_commit_seconds')}
        seconds['direct_budget_seconds'] = budget['query_append_budget_seconds']
        for source, target in ((seconds, cell['seconds']), (row['rank_stages_seconds'], cell['rank_stages_seconds']),
                               (part['append_exclusive_seconds'], cell['append_parts_seconds'])):
            for name, value in source.items():
                target[name] = target.get(name, 0.) + value
        query_cost = row['verification_seconds'] + budget['append_without_commit_or_budget_seconds']
        cell['max_verify_append_excluding_direct_budget_seconds'] = max(
            cell['max_verify_append_excluding_direct_budget_seconds'], query_cost)
    if any(cell['measured'] != quotas[name]['planned_new_queries'] for name, cell in cells.items()):
        raise ValueError('Incomplete per-cell cost observations')
    return {'cells': cells, 'setup_seconds': measured['setup_seconds'],
            'tail_flush_and_eof_seal_seconds': measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds': sum(event['seconds'] for event in measured['chunk_commits']),
            'budget_contexts': detail['budget']['by_context']}
