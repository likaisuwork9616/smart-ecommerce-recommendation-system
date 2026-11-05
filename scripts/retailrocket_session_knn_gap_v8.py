"""Selection and coverage for the two pre-registered V8 workload cells."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_gap_v7 import _historical
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell


CELLS = ('0000/n3/v2', '0000/n3/v3')
PREFIX = b'k1-gap-v8-20261105\x00'


def _quotas(spec):
    values = spec['quotas']
    quotas = {q['cell']: q for q in values}
    rule = spec['selection']
    if (len(values) != 2 or set(quotas) != set(CELLS)
            or (rule['quota'], rule['planned_unique_queries'], rule['prefix_with_terminator'].encode('ascii'))
                != (4, 8, PREFIX)
            or any(q['planned_new_queries'] != 4 for q in values)):
        raise ValueError('Expected four new keys in each of the two frozen V8 cells')
    return quotas


def _history(prior64, frozen48, prior34):
    a, b, c = (_historical(group['probes']) for group in (prior64, frozen48, prior34))
    for identity in a.keys() & b.keys():
        if any(a[identity][f] != b[identity][f] for f in ('key','history_sha256')):
            raise ValueError('Overlapping historical identities disagree')
    if c.keys() & (a.keys() | b.keys()):
        raise ValueError('The previous 34 probes overlap an earlier sample')
    return a | b | c, b, c


def select_gap_roster(path, prior64, frozen48, prior34, specification, watch=lambda: None):
    """Stream the bound structural roster; retain only four salted minima per cell."""
    quotas = _quotas(specification)
    history, masks, fine = _history(prior64, frozen48, prior34)
    population = frozen48['population']
    thresholds = population['p90_nearest_rank']
    counts, excluded = Counter(), Counter()
    best = {c: [] for c in CELLS}
    seen = set()
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            key = row['key_sha256']
            if (row['original_ordinal'] != ordinal or _sha(row['key']) != key or key in seen
                    or any(type(row[name]) is not int or row[name] < 0 for name in DIMENSIONS)):
                raise ValueError('Invalid or duplicate structural identity/workload')
            seen.add(key)
            mask = ''.join('1' if row[f] > 0 and row[f] >= thresholds[f] else '0' for f in DIMENSIONS)
            cell = _cell(row, mask, 'neighbor_vote_grid')
            if key in history:
                if any(history[key][f] != row[f] for f in ('key','history_sha256')):
                    raise ValueError('Historical identity differs from structural row')
                if key in masks and (masks[key]['cell'], masks[key]['original_ordinal']) != (mask,ordinal):
                    raise ValueError('Previous 48 probe mask or ordinal differs')
                if key in fine and (fine[key]['cell'], fine[key]['original_ordinal']) != (cell,ordinal):
                    raise ValueError('Previous 34 probe cell or ordinal differs')
                if cell in quotas and (key in masks or key in fine):
                    raise ValueError('Requested V8 cell already has a V6/V7 probe')
            if cell not in quotas:
                continue
            counts[cell] += 1
            if key in history:
                excluded[cell] += 1
                continue
            token = hashlib.sha256(PREFIX + bytes.fromhex(key)).digest()
            bucket = best[cell]
            bucket.append((token, ordinal, dict(row, cell=cell)))
            bucket.sort(key=lambda item: item[:2])
            del bucket[4:]
    if (digest.hexdigest() != population['roster_sha256'] or len(seen) != population['total_queries']
            or not history.keys() <= seen):
        raise ValueError('Structural roster length, SHA or exclusion inventory differs')
    selected = []
    for cell, quota in quotas.items():
        if (counts[cell] != quota['population'] or excluded[cell] != quota['historical_exclusions']
                or counts[cell]-excluded[cell] != quota['eligible'] or len(best[cell]) != 4):
            raise ValueError('Registered cell population, exclusions or capacity changed')
        selected.extend(row for _,_,row in best[cell])
    return {'probes':sorted(selected,key=lambda r:r['original_ordinal']), 'roster_sha256':digest.hexdigest()}


def audit_gap_order(path, selection, prior64, frozen48, prior34, specification, watch=lambda: None):
    """Reproduce complete selected rows by independently sorting every eligible key."""
    quotas = _quotas(specification)
    excluded = {p['key_sha256'] for group in (prior64, frozen48, prior34) for p in group['probes']}
    candidates = {c:[] for c in quotas}
    digest = hashlib.sha256()
    thresholds = frozen48['population']['p90_nearest_rank']
    with Path(path).open('rb') as stream:
        for ordinal,line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            n = row['eligible_neighbors']
            v = row['vote_memberships_upper']
            if row['key_sha256'] in excluded or not 100 <= n <= 499 or not 100 <= v <= 1999:
                continue
            if any(row[f] > 0 and row[f] >= thresholds[f] for f in DIMENSIONS):
                continue
            cell = '0000/n3/v2' if v <= 499 else '0000/n3/v3'
            key = bytes.fromhex(row['key_sha256'])
            salt = specification['selection']['prefix_with_terminator'].encode('ascii')
            candidates[cell].append((hashlib.sha256(salt+key).hexdigest(), ordinal, dict(row,cell=cell)))
    expected = sorted((row for items in candidates.values()
                       for _,_,row in sorted(items,key=lambda item:item[:2])[:4]), key=lambda row:row['original_ordinal'])
    if (len(expected) != 8 or expected != selection['probes']
            or digest.hexdigest() != selection['roster_sha256']
            or digest.hexdigest() != frozen48['population']['roster_sha256']):
        raise ValueError('Independent full sort or sealed selected row differs')


def check_coverage(remaining, added_cells, total_cells=55, historic_unique=144, new_keys=8):
    if (set(added_cells) != set(CELLS) or not set(CELLS) <= remaining.keys() or new_keys != 8
            or any(c['population'] != remaining[k] or c['measured'] != 4 for k,c in added_cells.items())):
        raise ValueError('New coverage must account for two previously unrepresented cells')
    missing = {cell:n for cell,n in remaining.items() if cell not in added_cells}
    return ({'v6_plus_new_cells_with_sample':total_cells-len(missing),
             'v6_plus_new_unrepresented_population':sum(missing.values()),
             'distinct_historically_verified_queries':historic_unique+new_keys}, missing)


def sample_workload(probes, measured):
    """All eligible neighbors fit below k=500, so the vote upper sum is exact."""
    grouped = {cell:[] for cell in CELLS}
    for probe, observation in zip(probes, measured['queries'], strict=True):
        work = observation['sql_workload']
        neighbors = probe['eligible_neighbors']
        upper = probe['vote_memberships_upper']
        if (probe['key_sha256'] != observation['key_sha256']
                or probe['original_ordinal'] != observation['original_ordinal']
                or not 100 <= neighbors <= 499 or work['sql_selected_rows_inserted'] != neighbors
                or work['sql_vote_membership_rows_returned'] != upper
                or not 0 <= work['exact_vote_additions'] <= upper):
            raise ValueError('Observed SQL work differs from the eight registered queries')
        grouped[probe['cell']].append((neighbors,upper,work['exact_vote_additions']))
    result = {}
    for cell, observations in grouped.items():
        if len(observations) != 4:
            raise ValueError('Missing workload observations in selected fine cell')
        selected, votes, additions = zip(*observations)
        result[cell] = {'eligible_neighbors_min':min(selected),'eligible_neighbors_max':max(selected),
                        'vote_upper_min':min(votes),'vote_upper_max':max(votes),
                        'sql_selected_rows_inserted':sum(selected),'sql_vote_membership_rows_returned':sum(votes),
                        'exact_vote_additions':sum(additions)}
    return result


def compare_frames(folder, size):
    def frames(repeat):
        store = Path(folder)/f'repeat_{repeat}'/'verified_subset'
        for manifest in sorted((store/'chunks').glob('*.json')):
            payload = json.loads(manifest.read_bytes())['payload']['path']
            with (store/payload).open('rb') as stream:
                yield from stream
    count = 0
    for first, second in zip(frames(0),frames(1),strict=True):
        if first != second:
            raise ValueError('Corresponding scientific frames differ')
        count += 1
    if count != size:
        raise ValueError('Physical frame count differs')
