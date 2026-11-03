"""Target-blind refinements of the existing full V5 structural roster.

No new sample selection or prediction. Missing refined-cell timing remains
explicit; parent fallback is only a sensitivity scenario, never coverage.
"""
from bisect import bisect_left
from collections import Counter
import hashlib
import json
import math

from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS, POLICY


NEIGHBOR_UPPER = (0, 9, 99, 499, 999, 4999)
VOTE_UPPER = (0, 99, 499, 1999, 9999)
POLICIES = ('parent', 'neighbor_bands', 'neighbor_vote_grid')


def _cell(row, parent, policy):
    if policy == 'parent':
        return parent
    cell = parent+'/n'+str(bisect_left(NEIGHBOR_UPPER, row['eligible_neighbors']))
    if policy == 'neighbor_vote_grid':
        cell += '/v'+str(bisect_left(VOTE_UPPER, row['vote_memberships_upper']))
    return cell


def refine_roster(path, frozen, watch=lambda: None):
    population, probes = frozen['population'], frozen['probes']
    if population['selection_policy'] != POLICY or population['complete'] is not True:
        raise ValueError('A complete frozen V5 structural population is required')
    count = population['total_queries']
    wanted = {p['original_ordinal']: p for p in probes}
    if len(wanted) != len(probes) or not 0 < len(probes) <= 64:
        raise ValueError('Invalid frozen bounded sample')
    cells = {policy: {} for policy in POLICIES}
    digest = hashlib.sha256(); found = {}; parent_counts = Counter(); scanned = 0
    with open(path, 'rb') as stream:
        for line in stream:
            watch(); digest.update(line); row = json.loads(line)
            if row['original_ordinal'] != scanned:
                raise ValueError('Structural roster ordinal differs')
            scanned += 1
            if any(type(row[name]) is not int or row[name] < 0 for name in DIMENSIONS):
                raise ValueError('Invalid structural workload')
            parent = ''.join('1' if row[name] > 0 and row[name] >= population['p90_nearest_rank'][name]
                             else '0' for name in DIMENSIONS)
            parent_counts[parent] += 1
            for policy in POLICIES:
                name = _cell(row, parent, policy)
                bucket = cells[policy].setdefault(name, {'parent': parent, 'population_queries': 0,
                                                        'sample_subset_ordinals': []})
                bucket['population_queries'] += 1
            ordinal = row['original_ordinal']
            if ordinal in wanted:
                probe = wanted[ordinal]
                if any(probe[name] != row[name] for name in ('key', 'key_sha256', 'history_sha256', *DIMENSIONS)) or probe['cell'] != parent:
                    raise ValueError('Frozen sample identity/structure differs')
                found[ordinal] = row
    if (scanned != count or digest.hexdigest() != population['roster_sha256'] or set(found) != set(wanted)
            or any(parent_counts[k] != v['population_queries'] for k, v in population['cells'].items())):
        raise ValueError('Incomplete or changed frozen structural population')
    for subset, probe in enumerate(probes):
        row = found[probe['original_ordinal']]
        for policy in POLICIES:
            cells[policy][_cell(row, probe['cell'], policy)]['sample_subset_ordinals'].append(subset)
    return {'kind': 'v6_fixed_sample_structural_refinements', 'total_queries': count,
            'sample_queries': len(probes), 'cells': cells,
            'neighbor_inclusive_upper_bounds': list(NEIGHBOR_UPPER),
            'vote_inclusive_upper_bounds': list(VOTE_UPPER), 'tail_bin': 'greater than last bound',
            'targets_or_predictions_used': False, 'new_sample_keys': 0,
            'roster_sha256': digest.hexdigest()}


def summarize_refined(refined, frozen, measured, budget):
    probes = frozen['probes']; rows = measured['queries']; split = budget['rows']
    if (measured['committed_prefix_rows'] != 0 or measured['verified_subset_queries'] != len(probes)
            or len(rows) != len(probes) or len(split) != len(probes)):
        raise ValueError('A fresh complete fixed-sample measurement is required')
    costs = []
    for subset, (probe, row, part) in enumerate(zip(probes, rows, split)):
        if (row['subset_ordinal'] != subset or part['subset_ordinal'] != subset
                or row['original_ordinal'] != probe['original_ordinal'] or row['key_sha256'] != probe['key_sha256']):
            raise ValueError('Measured sample differs from the frozen selection')
        value = {'raw_verify_append': row['verification_seconds']+row['append_without_commit_seconds'],
                 'verify_append_without_direct_budget': row['verification_seconds']+part['append_without_commit_or_budget_seconds'],
                 'verification_only': row['verification_seconds'], 'rank_only': row['rank_seconds'],
                 'append_without_commit_or_budget': part['append_without_commit_or_budget_seconds']}
        if any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in value.values()):
            raise ValueError('Invalid query component timing')
        costs.append(value)
    parents = refined['cells']['parent']; summaries = {}
    for policy, cells in refined['cells'].items():
        if sum(c['population_queries'] for c in cells.values()) != refined['total_queries']:
            raise ValueError('Incomplete refined population')
        seen = sorted(i for c in cells.values() for i in c['sample_subset_ordinals'])
        if seen != list(range(len(probes))):
            raise ValueError('Incomplete/duplicate refined sample coverage')
        public = {}; uncovered = 0; scenarios = {name: {'sample_covered_seconds': 0., 'parent_fallback_seconds': 0.}
                                               for name in costs[0]}
        for name, cell in sorted(cells.items()):
            sample = cell['sample_subset_ordinals']; parent = parents[cell['parent']]
            if not sample:
                uncovered += cell['population_queries']
            observed = sample if sample else parent['sample_subset_ordinals']
            if not observed:
                raise ValueError('Parent sample missing for a populated cell')
            maxima = {component: max(costs[i][component] for i in observed) for component in costs[0]}
            bucket = 'sample_covered_seconds' if sample else 'parent_fallback_seconds'
            for component, maximum in maxima.items():
                scenarios[component][bucket] += cell['population_queries']*maximum
            public[name] = {'parent': cell['parent'], 'population_queries': cell['population_queries'],
                            'measured_queries': len(sample), 'uses_parent_fallback': not bool(sample),
                            'scenario_max_seconds': maxima}
        for value in scenarios.values():
            value['total_with_explicit_parent_fallback_seconds'] = math.fsum(value.values())
        summaries[policy] = {'nonempty_cells': len(cells), 'sample_covered_population': refined['total_queries']-uncovered,
                             'uncovered_population': uncovered, 'cells': public, 'scenarios': scenarios}
    return {'kind': 'fixed_48_refinement_sensitivity_only', 'policies': summaries,
            'projection': 'Population times observed sample maximum; uncovered cells explicitly borrow parent maximum. '
                          'Component maxima may occur on different queries and must not be added.',
            'full_readback_started': False, 'scientific_acceptance': False, 'reserved_test': 'locked', 'T_plan': None}
