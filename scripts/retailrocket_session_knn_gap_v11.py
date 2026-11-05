"""Target-blind V11 sample selection, work and timing checks for two n4 cells."""
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


CELLS = ('0001/n4/v3', '1101/n4/v5')
PREFIX = b'k1-gap-v11-20261105\x00'


def _quotas(spec):
    rule = spec['selection']
    quotas = {q['cell']: q for q in spec['quotas']}
    if ((rule['quota'], rule['planned_unique_queries'], rule['prefix_with_terminator'].encode('ascii')) != (4, 8, PREFIX)
            or len(spec['quotas']) != 2 or set(quotas) != set(CELLS)
            or any(q['planned_new_queries'] != 4 for q in quotas.values())):
        raise ValueError('Two registered V11 cells, four rows each and the frozen salt are required')
    return quotas


def select_gap_roster(path, prior64, frozen48, prior34, prior8_v8, prior8_v9, prior8_v10,
                      specification, watch=lambda: None):
    quotas = _quotas(specification)
    history, masks, fine = _all_history(prior64, frozen48, prior34, prior8_v8, prior8_v9)
    recent = _historical(prior8_v10['probes'])
    if history.keys() & recent.keys():
        raise ValueError('V10 overlaps a previous cohort')
    history.update(recent)
    fine.update(recent)
    population = frozen48['population']
    thresholds = population['p90_nearest_rank']
    counts, excluded = Counter(), Counter()
    seen = set()
    best = {cell: [] for cell in CELLS}
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or _sha(row['key']) != identity or identity in seen
                    or any(type(row[k]) is not int or row[k] < 0 for k in DIMENSIONS)):
                raise ValueError('Invalid structural identity, ordinal or workload')
            seen.add(identity)
            mask = ''.join('1' if row[k] > 0 and row[k] >= thresholds[k] else '0' for k in DIMENSIONS)
            cell = _cell(row, mask, 'neighbor_vote_grid')
            if identity in history:
                if any(history[identity][k] != row[k] for k in ('key', 'history_sha256')):
                    raise ValueError('Historical query identity differs from structural roster')
                for group, label in ((masks, mask), (fine, cell)):
                    if identity in group and (group[identity]['cell'],group[identity]['original_ordinal']) != (label,ordinal):
                        raise ValueError('Historical cell or ordinal differs')
                if cell in quotas and (identity in fine or identity in masks):
                    raise ValueError('Requested cell is already represented by a comparable probe')
            if cell not in quotas:
                continue
            counts[cell] += 1
            if identity in history:
                excluded[cell] += 1
                continue
            token = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
            best[cell].append((token, ordinal, dict(row, cell=cell)))
            best[cell].sort(key=lambda item:item[:2])
            del best[cell][4:]
    if (digest.hexdigest() != population['roster_sha256'] or len(seen) != population['total_queries']
            or not history.keys() <= seen):
        raise ValueError('Incomplete or changed structural/historical roster')
    probes = []
    for cell, q in quotas.items():
        if (counts[cell], excluded[cell], counts[cell]-excluded[cell], len(best[cell])) != (
                q['population'], q['historical_exclusions'], q['eligible'], 4):
            raise ValueError('Registered population, exclusion count or capacity differs')
        probes.extend(row for _,_,row in best[cell])
    return {'probes':sorted(probes,key=lambda row:row['original_ordinal']), 'roster_sha256':digest.hexdigest()}


def audit_gap_order(path, selection, prior64, frozen48, prior34, prior8_v8, prior8_v9, prior8_v10,
                    specification, watch=lambda: None):
    """Full sort with independent literal band rules; verify all chosen row fields."""
    eligible = {cell:[] for cell in _quotas(specification)}
    groups = (prior64, frozen48, prior34, prior8_v8, prior8_v9, prior8_v10)
    excluded = {p['key_sha256'] for g in groups for p in g['probes']}
    thresholds = frozen48['population']['p90_nearest_rank']
    salt = specification['selection']['prefix_with_terminator'].encode('ascii')
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal,line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if identity in excluded or not 500 <= row['eligible_neighbors'] <= 999:
                continue
            mask = ''.join(str(int(0 < row[k] and thresholds[k] <= row[k])) for k in DIMENSIONS)
            upper = row['vote_memberships_upper']
            if mask=='0001' and 500 <= upper <= 1999:
                cell = CELLS[0]
            elif mask=='1101' and upper >= 10000:
                cell = CELLS[1]
            else:
                continue
            order = hashlib.sha256(salt+bytes.fromhex(identity)).hexdigest()
            eligible[cell].append((order,ordinal,dict(row,cell=cell)))
    winners = sorted((row for group in eligible.values()
                      for _,_,row in sorted(group,key=lambda item:item[:2])[:4]),key=lambda r:r['original_ordinal'])
    if (len(winners) != 8 or winners != selection['probes'] or digest.hexdigest() != selection['roster_sha256']
            or digest.hexdigest() != frozen48['population']['roster_sha256']):
        raise ValueError('Independent selected rows or structural SHA differ')


def check_coverage(remaining, added_cells, total_cells=55, historic_unique=168, new_keys=8):
    if (set(added_cells) != set(CELLS) or not set(CELLS) <= remaining.keys() or new_keys != 8
            or any(c['population'] != remaining[k] or c['measured'] != 4 for k,c in added_cells.items())):
        raise ValueError('Coverage requires four verified rows in each registered cell')
    missing = {k:v for k,v in remaining.items() if k not in added_cells}
    return {'v6_plus_new_cells_with_sample':total_cells-len(missing),
            'v6_plus_new_unrepresented_population':sum(missing.values()),
            'distinct_historically_verified_queries':historic_unique+new_keys}, missing


def _work(probe, row):
    work = row['sql_workload']
    neighbors, upper = probe['eligible_neighbors'], probe['vote_memberships_upper']
    valid_votes = ((probe['cell']==CELLS[0] and 500<=upper<=1999)
                   or (probe['cell']==CELLS[1] and upper>=10000))
    votes = work['sql_vote_membership_rows_returned']
    if (not valid_votes or not 500 <= neighbors <= 999
            or (probe['original_ordinal'],probe['key_sha256']) != (row['original_ordinal'],row['key_sha256'])
            or work['neighbor_pool_rows_hashed'] != neighbors or work['sql_selected_rows_inserted'] != 500
            or not 500 <= votes <= upper or (neighbors==500 and votes!=upper)
            or not 0 <= work['exact_vote_additions'] <= votes):
        raise ValueError('Eligible pool, top 500, vote bound or causal additions differ')
    return work


def sample_workload(probes, measured, predictions):
    grouped = {cell:[] for cell in CELLS}
    for p,r,pred in zip(probes,measured['queries'],predictions,strict=True):
        work = _work(p,r)
        grouped[p['cell']].append((p,work,_boundary(p,work,pred)))
    result = {}
    for cell,group in grouped.items():
        if len(group)!=4:
            raise ValueError('Incomplete sample workload')
        neighbors = [p['eligible_neighbors'] for p,w,b in group]
        bounds = [p['vote_memberships_upper'] for p,w,b in group]
        sums = {k:sum(w[k] for p,w,b in group) for k in
                ('sql_selected_rows_inserted','neighbor_pool_rows_hashed','sql_vote_membership_rows_returned','exact_vote_additions')}
        ties = sum(b[1] for p,w,b in group)
        removed = sum(b[2] for p,w,b in group)
        result[cell] = dict(sums, eligible_neighbors_min=min(neighbors),eligible_neighbors_max=max(neighbors),
                vote_upper_min=min(bounds),vote_upper_max=max(bounds),vote_upper_sum=sum(bounds),
                vote_upper_slack=sum(bounds)-sums['sql_vote_membership_rows_returned'],
                exact500_queries=neighbors.count(500),over500_queries=sum(n>500 for n in neighbors),
                boundary_queries=sum(b[0] for p,w,b in group),boundary_ties_total=ties,
                boundary_ties_selected=ties-removed,boundary_ties_excluded=removed)
    return result


def summarize_gap_cost(measured, detail, selection, specification):
    probes = selection['probes']
    cells = {name:{'population':q['population'],'measured':0,'seconds':{},'rank_stages_seconds':{},
                   'append_parts_seconds':{},'max_verify_append_excluding_direct_budget_seconds':0.}
             for name,q in _quotas(specification).items()}
    if len(probes)!=8 or measured['verified_subset_queries']!=8 or measured['committed_prefix_rows']!=0:
        raise ValueError('Fresh complete eight-query measurement required')
    for i,(probe,row,part,budget) in enumerate(zip(probes,measured['queries'],detail['rows'],detail['budget']['rows'],strict=True)):
        work = _work(probe,row)
        if (any(r['subset_ordinal']!=i for r in (row,part,budget))
                or work['sql_overlap_membership_matches']!=probe['posting_work']
                or work['causal_catalog_candidates']!=probe['causal_candidates']):
            raise ValueError('Measured ordinal, postings or causal catalog differs')
        cell = cells[probe['cell']]
        cell['measured'] += 1
        seconds = {k:row[k] for k in ('verification_seconds','rank_seconds','checkpoint_append_seconds',
                                      'append_without_commit_seconds','chunk_commit_seconds')}
        seconds['direct_budget_seconds'] = budget['query_append_budget_seconds']
        for name,values in (('seconds',seconds),('rank_stages_seconds',row['rank_stages_seconds']),
                            ('append_parts_seconds',part['append_exclusive_seconds'])):
            for k,v in values.items():
                cell[name][k] = cell[name].get(k,0.)+v
        cost = row['verification_seconds']+budget['append_without_commit_or_budget_seconds']
        cell['max_verify_append_excluding_direct_budget_seconds'] = max(cell['max_verify_append_excluding_direct_budget_seconds'],cost)
    if any(c['measured']!=4 for c in cells.values()):
        raise ValueError('Incomplete cell cost coverage')
    return {'cells':cells,'setup_seconds':measured['setup_seconds'],
            'tail_flush_and_eof_seal_seconds':measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds':sum(c['seconds'] for c in measured['chunk_commits']),
            'budget_contexts':detail['budget']['by_context']}
