"""Target-blind V10 selection and cost summaries for two capped 1111 cells."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_gap_v7 import _historical
from scripts.retailrocket_session_knn_gap_v8 import compare_frames, _history
from scripts.retailrocket_session_knn_gap_v9 import _boundary
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell


CELLS = ('1111/n4/v4', '1111/n5/v4')
PREFIX = b'k1-gap-v10-20261105\x00'


def _quotas(specification):
    rule = specification['selection']
    quotas = {q['cell']: q for q in specification['quotas']}
    if (rule['quota'] != 4 or rule['planned_unique_queries'] != 8
            or rule['prefix_with_terminator'].encode('ascii') != PREFIX
            or len(specification['quotas']) != 2 or set(quotas) != set(CELLS)
            or any(q['planned_new_queries'] != 4 for q in quotas.values())):
        raise ValueError('Expected two registered V10 cells, four queries each and the fixed salt')
    return quotas


def _all_history(prior64, frozen48, prior34, prior8_v8, prior8_v9):
    history, masks, fine = _history(prior64, frozen48, prior34)
    for group in (prior8_v8, prior8_v9):
        recent = _historical(group['probes'])
        if history.keys() & recent.keys():
            raise ValueError('A later historical probe cohort overlaps an earlier one')
        history.update(recent)
        fine.update(recent)
    return history, masks, fine


def select_gap_roster(path, prior64, frozen48, prior34, prior8_v8, prior8_v9, specification,
                      watch=lambda: None):
    """Validate every row and historical identity while retaining four salted minima per cell."""
    quotas = _quotas(specification)
    history, masks, fine = _all_history(prior64, frozen48, prior34, prior8_v8, prior8_v9)
    population = frozen48['population']
    thresholds = population['p90_nearest_rank']
    seen = set()
    counts, excluded = Counter(), Counter()
    best = {cell: [] for cell in CELLS}
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or _sha(row['key']) != identity or identity in seen
                    or any(type(row[f]) is not int or row[f] < 0 for f in DIMENSIONS)):
                raise ValueError('Invalid structural identity, ordinal or workload')
            seen.add(identity)
            mask = ''.join('1' if row[f] > 0 and row[f] >= thresholds[f] else '0' for f in DIMENSIONS)
            cell = _cell(row, mask, 'neighbor_vote_grid')
            if identity in history:
                if any(history[identity][f] != row[f] for f in ('key', 'history_sha256')):
                    raise ValueError('Historical query identity differs from structural roster')
                for cohort, label in ((masks, mask), (fine, cell)):
                    if identity in cohort and (cohort[identity]['cell'],cohort[identity]['original_ordinal']) != (label,ordinal):
                        raise ValueError('Historical cell or ordinal differs from structural roster')
                if cell in quotas and (identity in masks or identity in fine):
                    raise ValueError('A target cell already has a comparable verified query')
            if cell not in quotas:
                continue
            counts[cell] += 1
            if identity in history:
                excluded[cell] += 1
                continue
            token = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
            best[cell].append((token, ordinal, dict(row, cell=cell)))
            best[cell].sort(key=lambda entry: entry[:2])
            del best[cell][4:]
    if (digest.hexdigest() != population['roster_sha256'] or len(seen) != population['total_queries']
            or not history.keys() <= seen):
        raise ValueError('Incomplete or changed structural/historical roster')
    probes = []
    for cell, q in quotas.items():
        if (counts[cell], excluded[cell], counts[cell]-excluded[cell], len(best[cell])) != (
                q['population'], q['historical_exclusions'], q['eligible'], 4):
            raise ValueError('Registered cell population, exclusions or quota differs')
        probes.extend(row for _,_,row in best[cell])
    return {'probes': sorted(probes,key=lambda r:r['original_ordinal']), 'roster_sha256': digest.hexdigest()}


def audit_gap_order(path, selection, prior64, frozen48, prior34, prior8_v8, prior8_v9,
                    specification, watch=lambda: None):
    """Independent full sort with literal target boundaries and separately computed tokens."""
    candidates = {cell: [] for cell in _quotas(specification)}
    excluded = {row['key_sha256'] for group in (prior64, frozen48, prior34, prior8_v8, prior8_v9)
                for row in group['probes']}
    thresholds = frozen48['population']['p90_nearest_rank']
    prefix = specification['selection']['prefix_with_terminator'].encode('ascii')
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            neighbors, upper = row['eligible_neighbors'], row['vote_memberships_upper']
            if (identity in excluded or not 500 <= neighbors <= 4999 or not 2000 <= upper <= 9999
                    or any(row[name] <= 0 or row[name] < thresholds[name] for name in DIMENSIONS)):
                continue
            cell = CELLS[0] if neighbors <= 999 else CELLS[1]
            rank = hashlib.sha256(prefix+bytes.fromhex(identity)).hexdigest()
            candidates[cell].append((rank, ordinal, dict(row, cell=cell)))
    winners = sorted((row for group in candidates.values()
                      for _,_,row in sorted(group, key=lambda item:item[:2])[:4]),
                     key=lambda r:r['original_ordinal'])
    if (len(winners) != 8 or winners != selection['probes'] or digest.hexdigest() != selection['roster_sha256']
            or digest.hexdigest() != frozen48['population']['roster_sha256']):
        raise ValueError('Independent selection, selected metadata or structural SHA differs')


def check_coverage(remaining, added_cells, total_cells=55, historic_unique=160, new_keys=8):
    if (set(added_cells) != set(CELLS) or not set(CELLS) <= remaining.keys() or new_keys != 8
            or any(c['population'] != remaining[k] or c['measured'] != 4 for k,c in added_cells.items())):
        raise ValueError('Coverage must add four verified probes in each registered gap')
    missing = {cell:n for cell,n in remaining.items() if cell not in added_cells}
    return {'v6_plus_new_cells_with_sample':total_cells-len(missing),
            'v6_plus_new_unrepresented_population':sum(missing.values()),
            'distinct_historically_verified_queries':historic_unique+new_keys}, missing


def _work(probe, row):
    work = row['sql_workload']
    neighbors, upper = probe['eligible_neighbors'], probe['vote_memberships_upper']
    cell = probe['cell']
    in_band = (cell == CELLS[0] and 500 < neighbors <= 999) or (cell == CELLS[1] and 1000 <= neighbors <= 4999)
    votes = work['sql_vote_membership_rows_returned']
    if (not in_band or not 2000 <= upper <= 9999
            or (row['original_ordinal'],row['key_sha256']) != (probe['original_ordinal'],probe['key_sha256'])
            or work['neighbor_pool_rows_hashed'] != neighbors or work['sql_selected_rows_inserted'] != 500
            or not 500 <= votes <= upper or not 0 <= work['exact_vote_additions'] <= votes):
        raise ValueError('Capped neighbor pool, selected rows, causal additions or membership bound differs')
    return work


def sample_workload(probes, measured, predictions):
    groups = {cell: [] for cell in CELLS}
    for probe, row, pred in zip(probes, measured['queries'], predictions, strict=True):
        work = _work(probe, row)
        frontier = _boundary(probe, work, pred)
        groups[probe['cell']].append((probe, work, frontier))
    summary = {}
    for cell, group in groups.items():
        if len(group) != 4:
            raise ValueError('Missing one or more selected cell observations')
        neighbors = [p['eligible_neighbors'] for p,_,_ in group]
        bounds = [p['vote_memberships_upper'] for p,_,_ in group]
        sums = {name:sum(w[name] for _,w,_ in group) for name in
                ('neighbor_pool_rows_hashed','sql_selected_rows_inserted','sql_vote_membership_rows_returned','exact_vote_additions')}
        ties = sum(b[1] for _,_,b in group)
        removed = sum(b[2] for _,_,b in group)
        summary[cell] = dict(sums, eligible_neighbors_min=min(neighbors), eligible_neighbors_max=max(neighbors),
                vote_upper_min=min(bounds), vote_upper_max=max(bounds), vote_upper_sum=sum(bounds),
                vote_upper_slack=sum(bounds)-sums['sql_vote_membership_rows_returned'],
                boundary_queries=sum(b[0] for _,_,b in group), boundary_ties_total=ties,
                boundary_ties_selected=ties-removed, boundary_ties_excluded=removed)
    return summary


def summarize_gap_cost(measured, detail, selection, specification):
    probes = selection['probes']
    cells = {name:{'population':q['population'], 'measured':0, 'seconds':{}, 'rank_stages_seconds':{},
                   'append_parts_seconds':{}, 'max_verify_append_excluding_direct_budget_seconds':0.}
             for name,q in _quotas(specification).items()}
    if len(probes) != 8 or measured['verified_subset_queries'] != 8 or measured['committed_prefix_rows'] != 0:
        raise ValueError('A fresh complete eight-query verification is required')
    for i,(probe,row,part,budget) in enumerate(zip(probes, measured['queries'], detail['rows'],
                                                    detail['budget']['rows'], strict=True)):
        work = _work(probe,row)
        if (any(r['subset_ordinal'] != i for r in (row,part,budget))
                or work['sql_overlap_membership_matches'] != probe['posting_work']
                or work['causal_catalog_candidates'] != probe['causal_candidates']):
            raise ValueError('Frozen subset order, posting work or causal catalog differs')
        cell = cells[probe['cell']]
        cell['measured'] += 1
        raw = {name:row[name] for name in ('verification_seconds','rank_seconds','checkpoint_append_seconds',
                                           'append_without_commit_seconds','chunk_commit_seconds')}
        raw['direct_budget_seconds'] = budget['query_append_budget_seconds']
        for label, values in (('seconds',raw),('rank_stages_seconds',row['rank_stages_seconds']),
                              ('append_parts_seconds',part['append_exclusive_seconds'])):
            for name,value in values.items():
                cell[label][name] = cell[label].get(name,0.) + value
        query_cost = row['verification_seconds'] + budget['append_without_commit_or_budget_seconds']
        cell['max_verify_append_excluding_direct_budget_seconds'] = max(
            cell['max_verify_append_excluding_direct_budget_seconds'],query_cost)
    if any(cell['measured'] != 4 for cell in cells.values()):
        raise ValueError('Incomplete cell cost coverage')
    return {'cells':cells, 'setup_seconds':measured['setup_seconds'],
            'tail_flush_and_eof_seal_seconds':measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds':sum(c['seconds'] for c in measured['chunk_commits']),
            'budget_contexts':detail['budget']['by_context']}
