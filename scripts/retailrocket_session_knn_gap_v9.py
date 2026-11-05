"""Fixed two-cell selection and exact k=500 workload checks for V9."""
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_gap_v7 import _historical
from scripts.retailrocket_session_knn_gap_v8 import _history, compare_frames
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell


CELLS = ('1101/n5/v5', '0010/n3/v2')
PREFIX = b'k1-gap-v9-20261105\x00'


def _quotas(spec):
    values = spec['quotas']
    quotas = {r['cell']: r for r in values}
    rule = spec['selection']
    if (len(values) != 2 or set(quotas) != set(CELLS)
            or (rule['quota'], rule['planned_unique_queries'], rule['prefix_with_terminator'].encode('ascii')) != (4, 8, PREFIX)
            or any(r['planned_new_queries'] != 4 for r in values)):
        raise ValueError('Expected the registered V9 two cells, four each and fixed salt')
    return quotas


def select_gap_roster(path, prior64, frozen48, prior34, prior8, specification, watch=lambda: None):
    quotas = _quotas(specification)
    history, masks, low = _history(prior64, frozen48, prior34)
    recent = _historical(prior8['probes'])
    if history.keys() & recent.keys():
        raise ValueError('Previous V8 sample overlaps historical keys')
    history = history | recent
    represented = low | recent
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
                raise ValueError('Structural identity, workload or ordinal differs')
            seen.add(identity)
            parent = ''.join('1' if row[f] > 0 and row[f] >= thresholds[f] else '0' for f in DIMENSIONS)
            cell = _cell(row, parent, 'neighbor_vote_grid')
            if identity in history:
                if any(history[identity][f] != row[f] for f in ('key','history_sha256')):
                    raise ValueError('Historical identity differs from roster')
                for group, label in ((masks,parent),(represented,cell)):
                    if identity in group and (group[identity]['cell'],group[identity]['original_ordinal']) != (label,ordinal):
                        raise ValueError('Historical cell or original ordinal differs')
                if cell in quotas and (identity in masks or identity in represented):
                    raise ValueError('Registered cell already has a comparable probe')
            if cell not in quotas:
                continue
            counts[cell] += 1
            if identity in history:
                excluded[cell] += 1
                continue
            order = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
            best[cell].append((order,ordinal,dict(row,cell=cell)))
            best[cell].sort(key=lambda item:item[:2])
            del best[cell][4:]
    if (digest.hexdigest() != population['roster_sha256'] or len(seen) != population['total_queries']
            or not history.keys() <= seen):
        raise ValueError('Roster EOF, digest, or historical union changed')
    probes = []
    for cell, quota in quotas.items():
        if (counts[cell], excluded[cell], counts[cell]-excluded[cell], len(best[cell])) != (
                quota['population'], quota['historical_exclusions'], quota['eligible'], 4):
            raise ValueError('Registered capacity or quota changed')
        probes.extend(x[2] for x in best[cell])
    return {'probes':sorted(probes,key=lambda x:x['original_ordinal']), 'roster_sha256':digest.hexdigest()}


def audit_gap_order(path, selection, prior64, frozen48, prior34, prior8, specification, watch=lambda: None):
    """Full independent sort, using literal cell boundaries rather than V6 bin helpers."""
    candidates = {c:[] for c in _quotas(specification)}
    excluded = {r['key_sha256'] for g in (prior64,frozen48,prior34,prior8) for r in g['probes']}
    threshold = frozen48['population']['p90_nearest_rank']
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            if row['key_sha256'] in excluded:
                continue
            n,v = row['eligible_neighbors'],row['vote_memberships_upper']
            mask = ''.join(str(int(row[d] != 0 and row[d] >= threshold[d])) for d in DIMENSIONS)
            if mask == '1101' and 1000 <= n <= 4999 and v >= 10000:
                cell = CELLS[0]
            elif mask == '0010' and 100 <= n <= 499 and 100 <= v <= 499:
                cell = CELLS[1]
            else:
                continue
            salt = specification['selection']['prefix_with_terminator'].encode('ascii')
            order = hashlib.sha256(salt+bytes.fromhex(row['key_sha256'])).hexdigest()
            candidates[cell].append((order,ordinal,dict(row,cell=cell)))
    winners = sorted((row for group in candidates.values() for _,_,row in sorted(group,key=lambda x:x[:2])[:4]),
                     key=lambda row:row['original_ordinal'])
    if (len(winners) != 8 or winners != selection['probes'] or digest.hexdigest() != selection['roster_sha256']
            or digest.hexdigest() != frozen48['population']['roster_sha256']):
        raise ValueError('Independent sorted V9 selection or source digest differs')


def check_coverage(remaining, added_cells, total_cells=55, historic_unique=152, new_keys=8):
    if (set(added_cells) != set(CELLS) or not set(CELLS) <= remaining.keys() or new_keys != 8
            or any(c['population'] != remaining[k] or c['measured'] != 4 for k,c in added_cells.items())):
        raise ValueError('Completed V9 sample must add only its two registered cells')
    missing = {cell:n for cell,n in remaining.items() if cell not in added_cells}
    return {'v6_plus_new_cells_with_sample':total_cells-len(missing),
            'v6_plus_new_unrepresented_population':sum(missing.values()),
            'distinct_historically_verified_queries':historic_unique+new_keys}, missing


def _work(probe, row):
    work = row['sql_workload']
    neighbors, upper = probe['eligible_neighbors'], probe['vote_memberships_upper']
    cap = min(500,neighbors)
    votes = work['sql_vote_membership_rows_returned']
    high = probe['cell'] == CELLS[0]
    valid_cell = ((1000 <= neighbors <= 4999 and upper >= 10000) if high else
                  (probe['cell'] == CELLS[1] and 100 <= neighbors <= 499 and 100 <= upper <= 499))
    if (not valid_cell or row['original_ordinal'] != probe['original_ordinal'] or row['key_sha256'] != probe['key_sha256']
            or work['sql_selected_rows_inserted'] != cap or work['neighbor_pool_rows_hashed'] != neighbors
            or not cap <= votes <= upper or (neighbors <= 500 and votes != upper)
            or not 0 <= work['exact_vote_additions'] <= votes):
        raise ValueError('Actual eligible pool, selected count or vote membership bound differs')
    return work


def _boundary(probe, work, pred):
    """Cross-check the actual verified V4 scientific frame, including its selected frontier."""
    eligible = probe['eligible_neighbors']
    cap = min(eligible,500)
    selected = pred['selected_neighbors']
    digest = pred['neighbor_pool_sha256']
    if (pred['eligible_neighbors'] != eligible or pred['selected_neighbor_count'] != cap or len(selected) != cap
            or pred['vote_memberships'] != work['sql_vote_membership_rows_returned']
            or type(digest) is not str or len(digest) != 64 or any(ch not in '0123456789abcdef' for ch in digest)):
        raise ValueError('Verified prediction differs from the complete eligible pool/work')
    order, identities = [], set()
    selected_memberships = 0
    for member in selected:
        key = member['key']
        ident = (int(key[0]),key[1])
        inter, union = member['intersection'],member['union']
        if ident in identities or key == probe['key'][:2] or not 0 < inter <= union:
            raise ValueError('Selected duplicate, current session or invalid Jaccard set size')
        identities.add(ident)
        similarity = Fraction(inter,union)
        if member['similarity'] != [similarity.numerator,similarity.denominator]:
            raise ValueError('Selected exact similarity differs')
        order.append((-similarity,ident))
        selected_memberships += union-pred['history_size']+inter
    if order != sorted(order) or selected_memberships != pred['vote_memberships']:
        raise ValueError('Selected exact ordering or membership sizes differ')
    ties = pred['boundary_ties_total']
    removed = pred['boundary_ties_excluded']
    if cap == 500:
        boundary = selected[-1]['similarity']
        chosen_ties = sum(member['similarity']==boundary for member in selected)
        if (pred['boundary_similarity'] != boundary or not 0 <= removed <= eligible-cap
                or ties != chosen_ties+removed):
            raise ValueError('500-neighbor frontier or tie accounting differs')
    elif pred['boundary_similarity'] is not None or ties != 0 or removed != 0:
        raise ValueError('Unexpected 500-neighbor frontier in an uncapped sample')
    if eligible <= 500:
        h = hashlib.sha256()
        for m in sorted(selected,key=lambda x:(int(x['key'][0]),x['key'][1])):
            data = json.dumps([m['key'],m['intersection'],m['union']],separators=(',',':'),ensure_ascii=False)
            h.update((data+'\n').encode('utf-8'))
        if h.hexdigest() != digest:
            raise ValueError('Complete uncapped neighbor pool SHA differs')
    return int(cap==500),ties,removed


def sample_workload(probes, measured, predictions):
    grouped = {c:[] for c in CELLS}
    for probe,row,pred in zip(probes,measured['queries'],predictions,strict=True):
        work = _work(probe,row)
        boundary = _boundary(probe,work,pred)
        grouped[probe['cell']].append((probe,work,boundary))
    result = {}
    for cell, rows in grouped.items():
        if len(rows) != 4:
            raise ValueError('Incomplete V9 workload observations')
        neighbors = [p['eligible_neighbors'] for p,w,b in rows]
        bounds = [p['vote_memberships_upper'] for p,w,b in rows]
        totals = {f:sum(w[f] for _,w,_ in rows) for f in ('neighbor_pool_rows_hashed','sql_selected_rows_inserted',
                    'sql_vote_membership_rows_returned','exact_vote_additions')}
        result[cell] = dict(totals,eligible_neighbors_min=min(neighbors),eligible_neighbors_max=max(neighbors),
            vote_upper_min=min(bounds),vote_upper_max=max(bounds),vote_upper_sum=sum(bounds),
            boundary_queries=sum(b[0] for p,w,b in rows),boundary_ties_total=sum(b[1] for p,w,b in rows),
            boundary_ties_excluded=sum(b[2] for p,w,b in rows))
    return result


def summarize_gap_cost(measured, detail, selection, specification):
    probes = selection['probes']
    cells = {k:{'population':v['population'],'measured':0,'seconds':{},'rank_stages_seconds':{},
                'append_parts_seconds':{},'max_verify_append_excluding_direct_budget_seconds':0.}
             for k,v in _quotas(specification).items()}
    if len(probes) != 8 or measured['verified_subset_queries'] != 8 or measured['committed_prefix_rows']:
        raise ValueError('Fresh complete eight-query measurement required')
    for i,(probe,row,parts,budget) in enumerate(zip(probes,measured['queries'],detail['rows'],detail['budget']['rows'],strict=True)):
        work = _work(probe,row)
        if (any(r['subset_ordinal'] != i for r in (row,parts,budget))
                or work['sql_overlap_membership_matches'] != probe['posting_work']
                or work['causal_catalog_candidates'] != probe['causal_candidates']):
            raise ValueError('Frozen ordinal or structural scan differs')
        cell = cells[probe['cell']]
        cell['measured'] += 1
        durations = {f:row[f] for f in ('verification_seconds','rank_seconds','checkpoint_append_seconds',
                                       'append_without_commit_seconds','chunk_commit_seconds')}
        durations['direct_budget_seconds'] = budget['query_append_budget_seconds']
        for name,values in [('seconds',durations),('rank_stages_seconds',row['rank_stages_seconds']),
                           ('append_parts_seconds',parts['append_exclusive_seconds'])]:
            for k,v in values.items():
                cell[name][k] = cell[name].get(k,0.)+v
        query_time = row['verification_seconds']+budget['append_without_commit_or_budget_seconds']
        cell['max_verify_append_excluding_direct_budget_seconds'] = max(cell['max_verify_append_excluding_direct_budget_seconds'],query_time)
    if any(c['measured'] != 4 for c in cells.values()):
        raise ValueError('Incomplete per-cell measurements')
    return {'cells':cells,'setup_seconds':measured['setup_seconds'],
            'tail_flush_and_eof_seal_seconds':measured['tail_flush_and_eof_seal_seconds'],
            'all_chunk_commit_seconds':sum(c['seconds'] for c in measured['chunk_commits']),
            'budget_contexts': detail['budget']['by_context']}
