"""Read-only aggregation of frozen V6--V16 engineering costs, without new ranking."""
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import re
from statistics import median

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import NEIGHBOR_UPPER, VOTE_UPPER, _cell


METRICS = ('verification', 'rank', 'vote_sql_and_accumulation', 'checkpoint_append',
           'append_without_commit', 'direct_budget', 'append_without_commit_or_budget',
           'core', 'query_nested_commit')
COHORTS = {f'V{v}': {'queries': 48 if v == 6 else 34 if v == 7 else 10 if v == 16 else 8,
                    'repeats': 3 if v == 6 else 2} for v in range(6, 17)}
HEX = re.compile(r'[0-9a-f]{64}\Z')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _close(left, right):
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-10)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON object key')
        value[key] = item
    return value


def _decode(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))


def _path(root, record):
    name = record['path']
    if (type(name) is not str or not name or '\\' in name or ':' in name
            or any(p in ('', '.', '..') for p in name.split('/'))
            or type(record['bytes']) is not int or record['bytes'] < 0
            or type(record['sha256']) is not str or not HEX.fullmatch(record['sha256'])):
        raise ValueError('Invalid source descriptor')
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Missing source or source outside the project')
    return path


def read_bound(root, record):
    """Read one JSON source only when its saved bytes and SHA-256 still match."""
    path = _path(root, record)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']):
        raise ValueError('Bound source bytes or SHA-256 changed')
    return _decode(raw)


def verify_bindings(root, records, watch=lambda: None):
    """Verify every declared input, including non-JSON method files, without mutation."""
    names = set()
    for record in records:
        if record['path'] in names:
            raise ValueError('Duplicate source descriptor')
        names.add(record['path'])
        path = _path(root, record)
        before = path.stat()
        digest = hashlib.sha256()
        count = 0
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                watch()
                digest.update(block)
                count += len(block)
        after = path.stat()
        if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                or count != record['bytes'] or digest.hexdigest() != record['sha256']):
            raise ValueError('Bound source bytes or SHA-256 changed')
    return len(names)


def _check_seconds(seconds):
    if set(seconds) != set(METRICS) or any(not _finite(seconds[k]) for k in METRICS):
        raise ValueError('Missing, negative or nonfinite timing component')
    if (seconds['rank'] > seconds['verification'] or seconds['vote_sql_and_accumulation'] > seconds['rank']
            or seconds['direct_budget'] > seconds['append_without_commit']
            or not _close(seconds['checkpoint_append'], seconds['append_without_commit'] + seconds['query_nested_commit'])
            or not _close(seconds['append_without_commit'], seconds['direct_budget'] + seconds['append_without_commit_or_budget'])
            or not _close(seconds['core'], seconds['verification'] + seconds['append_without_commit_or_budget'])):
        raise ValueError('Nested timing components or same-row cost do not conserve')


def row_cost(row, budget_row, detail_row):
    """Keep nested components separate and calculate the core cost on the same query."""
    if (type(row['subset_ordinal']) is not int or row['subset_ordinal'] < 0
            or any(r['subset_ordinal'] != row['subset_ordinal'] for r in (budget_row, detail_row))):
        raise ValueError('Timing row ordinals differ')
    seconds = {
        'verification': row['verification_seconds'], 'rank': row['rank_seconds'],
        'vote_sql_and_accumulation': row['rank_stages_seconds']['sql_selected_votes_and_accumulation'],
        'checkpoint_append': row['checkpoint_append_seconds'],
        'append_without_commit': row['append_without_commit_seconds'],
        'direct_budget': budget_row['query_append_budget_seconds'],
        'append_without_commit_or_budget': budget_row['append_without_commit_or_budget_seconds'],
        'core': row['verification_seconds'] + budget_row['append_without_commit_or_budget_seconds'],
        'query_nested_commit': row['chunk_commit_seconds'],
    }
    _check_seconds(seconds)
    if (any(not _finite(v) for v in row['rank_stages_seconds'].values())
            or any(not _finite(v) for v in detail_row['append_exclusive_seconds'].values())
            or not _finite(detail_row['verification_other_seconds'])
            or any(not _close(budget_row[k], row[k]) for k in (
                'verification_seconds', 'append_without_commit_seconds', 'chunk_commit_seconds'))
            or not _close(sum(detail_row['append_exclusive_seconds'].values()), seconds['checkpoint_append'])
            or not _close(detail_row['verification_other_seconds'] + seconds['rank'], seconds['verification'])):
        raise ValueError('Detailed timing differs from its original enclosing row')
    return seconds


def normalize_repeat(cohort, repeat_index, probes, measured, observations, cell_by_identity):
    """Recompute the saved V6 append diagnostics and retain private paired-row identities."""
    if (not probes or measured['committed_prefix_rows'] != 0
            or measured['verified_subset_queries'] != len(probes) or len(measured['queries']) != len(probes)
            or len({p['key_sha256'] for p in probes}) != len(probes)
            or any(not _finite(event['seconds']) for event in (
                *measured['chunk_commits'], *observations['budget_events']))):
        raise ValueError('A fresh, complete, unique fixed cohort is required')
    observer = DetailedTimedStore.__new__(DetailedTimedStore)
    observer.append_events = observations['append_events']
    observer.budget_events = observations['budget_events']
    observer.commit_events = measured['chunk_commits']
    detail = observer.detailed_cost_summary(measured)
    if detail != observations['detail']:
        raise ValueError('Saved detail differs from recomputed raw timing events')
    rows = []
    for index, (probe, row, budget, part) in enumerate(zip(
            probes, measured['queries'], detail['budget']['rows'], detail['rows'], strict=True)):
        identity = probe['key_sha256']
        if (row['subset_ordinal'] != index or row['key_sha256'] != identity
                or row['original_ordinal'] != probe['original_ordinal'] or _sha(probe['key']) != identity
                or identity not in cell_by_identity):
            raise ValueError('Measured query identity or original ordinal differs from the fixed cohort')
        rows.append({'cohort': cohort, 'repeat_index': repeat_index, 'key_sha256': identity,
                     'original_ordinal': probe['original_ordinal'], 'cell': cell_by_identity[identity],
                     'seconds': row_cost(row, budget, part)})
    nested = math.fsum(row['seconds']['query_nested_commit'] for row in rows)
    all_commit = math.fsum(event['seconds'] for event in measured['chunk_commits'])
    direct = math.fsum(row['seconds']['direct_budget'] for row in rows)
    if any(not _finite(v) for v in (measured['setup_seconds'], measured['tail_flush_and_eof_seal_seconds'],
                                   all_commit, nested, detail['budget']['budget_seconds'])) or nested > all_commit:
        raise ValueError('Invalid setup, tail, commit or budget overhead')
    overheads = {'cohort': cohort, 'repeat_index': repeat_index,
                 'setup_seconds': measured['setup_seconds'],
                 'tail_flush_and_eof_seal_seconds': measured['tail_flush_and_eof_seal_seconds'],
                 'all_chunk_commit_seconds': all_commit, 'query_nested_commit_seconds': nested,
                 'final_flush_commit_seconds': all_commit - nested,
                 'all_budget_seconds': detail['budget']['budget_seconds'],
                 'direct_query_budget_seconds': direct, 'budget_by_context': detail['budget']['by_context']}
    return {'rows': rows, 'overheads': overheads}


def _stats(values):
    values = list(values)
    if not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError('A finite nonempty descriptive sample is required')
    total = math.fsum(values)
    return {'count': len(values), 'sum': total, 'mean': total / len(values),
            'minimum': min(values), 'median': median(values), 'maximum': max(values),
            'range': max(values) - min(values)}


def summarize_costs(populations, rows, overheads, expected_cohorts):
    """Aggregate identities privately; publish descriptive cell statistics only."""
    if (not populations or any(type(n) is not int or n <= 0 for n in populations.values())
            or not expected_cohorts or any(type(c[k]) is not int or c[k] <= (1 if k == 'repeats' else 0)
                for c in expected_cohorts.values() for k in ('queries', 'repeats'))):
        raise ValueError('Positive populations and preregistered cohort counts are required')
    grouped = defaultdict(dict)
    identities = {}
    ordinal_keys = {}
    cells = defaultdict(list)
    for row in rows:
        cohort, repeat = row['cohort'], row['repeat_index']
        identity, ordinal, cell = row['key_sha256'], row['original_ordinal'], row['cell']
        if (cohort not in expected_cohorts or type(repeat) is not int
                or not 0 <= repeat < expected_cohorts[cohort]['repeats'] or cell not in populations
                or type(ordinal) is not int or ordinal < 0
                or type(identity) is not str or not HEX.fullmatch(identity)):
            raise ValueError('Unexpected cohort, repeat, cell or query identity')
        _check_seconds(row['seconds'])
        key = (cohort, repeat)
        if (identity in grouped[key] or identities.get(identity, (cohort, ordinal, cell)) != (cohort, ordinal, cell)
                or ordinal_keys.get(ordinal, identity) != identity):
            raise ValueError('Duplicate query, overlapping cohorts or changed identity/cell')
        identities[identity] = (cohort, ordinal, cell)
        ordinal_keys[ordinal] = identity
        grouped[key][identity] = row
        cells[cell].append(row)
    required = {(name, i) for name, plan in expected_cohorts.items() for i in range(plan['repeats'])}
    if set(grouped) != required or set(cells) != set(populations):
        raise ValueError('Missing cohort repeat or populated cell; parent fallback is prohibited')
    for cohort, plan in expected_cohorts.items():
        first = set(grouped[cohort, 0])
        if len(first) != plan['queries'] or any(set(grouped[cohort, i]) != first for i in range(plan['repeats'])):
            raise ValueError('Repeat identities or fixed cohort size differ')
    if overheads:
        found = set()
        for item in overheads:
            key = (item['cohort'], item['repeat_index'])
            numeric = [v for name, v in item.items() if name.endswith('_seconds')]
            if key not in required or key in found or any(not _finite(v) for v in numeric):
                raise ValueError('Invalid or duplicate repeat overhead')
            found.add(key)
            samples = grouped[key].values()
            if (not _close(item['query_nested_commit_seconds'], math.fsum(r['seconds']['query_nested_commit'] for r in samples))
                    or not _close(item['direct_query_budget_seconds'], math.fsum(r['seconds']['direct_budget'] for r in samples))
                    or not _close(item['all_chunk_commit_seconds'], item['query_nested_commit_seconds'] + item['final_flush_commit_seconds'])):
                raise ValueError('Repeat overhead differs from the measured row components')
        if found != required:
            raise ValueError('Missing repeat overhead')
    public = {}
    weighted = {metric: {profile: {'cell_mean': 0., 'cell_maximum': 0.}
                        for profile in ('minimum', 'median', 'maximum')} for metric in METRICS}
    for cell, values in sorted(cells.items()):
        cohorts = {row['cohort'] for row in values}
        if len(cohorts) != 1:
            raise ValueError('Cross-window cohorts cannot be paired as cell repeats')
        cohort = next(iter(cohorts))
        count = expected_cohorts[cohort]['repeats']
        keys = sorted({row['key_sha256'] for row in values})
        if len(keys) > populations[cell]:
            raise ValueError('Distinct cell sample exceeds its structural population')
        repeats = [{key: grouped[cohort, i][key] for key in keys} for i in range(count)]
        by_repeat = [{'repeat_index': i, 'queries': len(keys), 'seconds': {
            metric: _stats(row['seconds'][metric] for row in group.values()) for metric in METRICS}}
            for i, group in enumerate(repeats)]
        temporal, scenario_inputs = {}, {}
        for metric in METRICS:
            per_query = {key: [group[key]['seconds'][metric] for group in repeats] for key in keys}
            profiles = {'minimum': [min(v) for v in per_query.values()],
                        'median': [median(v) for v in per_query.values()],
                        'maximum': [max(v) for v in per_query.values()]}
            pairs = []
            for first, second in combinations(range(count), 2):
                deltas = [per_query[key][second] - per_query[key][first] for key in keys]
                pairs.append({'from_repeat': first, 'to_repeat': second, 'delta_seconds': _stats(deltas),
                              'absolute_delta_seconds': _stats(abs(value) for value in deltas)})
            temporal[metric] = {
                'query_range_seconds': _stats(max(v) - min(v) for v in per_query.values()),
                'query_repeat_median_seconds': _stats(profiles['median']), 'pairs': pairs}
            scenario_inputs[metric] = {}
            for profile, sample in profiles.items():
                entry = {'cell_mean': math.fsum(sample) / len(sample), 'cell_maximum': max(sample)}
                scenario_inputs[metric][profile] = entry
                for statistic, value in entry.items():
                    weighted[metric][profile][statistic] += populations[cell] * value
        public[cell] = {'population_queries': populations[cell], 'distinct_queries': len(keys),
                        'repeat_observations': len(values), 'cohort': cohort, 'by_repeat': by_repeat,
                        'pooled_observations_seconds': {m: _stats(r['seconds'][m] for r in values) for m in METRICS},
                        'within_query_temporal': temporal, 'scenario_inputs_seconds': scenario_inputs}
    return {'scope': {'population_queries': sum(populations.values()), 'nonempty_cells': len(populations),
                      'distinct_queries': len(identities), 'repeat_observations': len(rows), 'parent_fallback_cells': 0},
            'cells': public, 'weighted_scenarios_seconds': weighted, 'overheads': overheads,
            'interpretation': {
                'query_spread': 'Per-repeat row statistics compare distinct fixed queries within one cell.',
                'temporal_variation': 'Ranges and signed later-minus-earlier pairs compare the same query within its original cohort only.',
                'weighting': 'For each query take repeat minimum, median or maximum; then take its cell mean or maximum and multiply by structural population. These six descriptive scenarios combine separate windows, not simultaneous benchmark repeats.',
                'accounting': 'Rank contains vote SQL and is nested in verification. Core is same-row verification plus append excluding nested commit and direct budget writes. Component scenarios must not be added. Setup, tail, all chunk commits and budget totals are separate diagnostics with overlapping containment; no overhead is added to weighted scenarios.',
                'limits': 'Fixed nonrandom samples and uncontrolled cache/system states provide no confidence interval, causal speedup, future latency guarantee or full-run runtime bound. Historical CPU/background-process telemetry was not retained; timing variation cannot be attributed to Ollama or any specific process.'},
            'full_readback_started': False, 'scientific_acceptance': False, 'reserved_test': 'locked', 'T_plan': None}


def load_manifest(root, manifest, watch=lambda: None):
    """Verify the frozen V17 inventory and normalize only its existing saved observations."""
    if (manifest['status'] != 'v17_cost_inventory_verified'
            or manifest['population']['total_queries'] != 166897 or manifest['population']['grid_cells'] != 55
            or manifest['population']['dimensions_in_mask_order'] != list(DIMENSIONS)
            or manifest['population']['neighbor_inclusive_upper_bounds'] != list(NEIGHBOR_UPPER)
            or manifest['population']['vote_inclusive_upper_bounds'] != list(VOTE_UPPER)):
        raise ValueError('Expected the complete frozen V17 cost inventory')
    records = manifest['inputs']
    verify_bindings(root, records, watch)
    bound = {record['path']: record for record in records}

    def read(record):
        if bound.get(record['path']) != record:
            raise ValueError('A manifest artifact is absent from its input bindings')
        watch()
        return read_bound(root, record)

    cohorts = manifest['cohorts']
    if ([c['cohort'] for c in cohorts] != list(COHORTS)
            or any((c['expected_queries'], c['expected_repeats']) != (COHORTS[c['cohort']]['queries'], COHORTS[c['cohort']]['repeats'])
                   for c in cohorts)):
        raise ValueError('The eleven original timing cohorts and repeat counts are required')
    selections, reports, wanted = {}, {}, {}
    for entry in cohorts:
        cohort = entry['cohort']
        report, selection = read(entry['report']), read(entry['selection'])
        read(entry['request'])
        expected_status = ('v6_same_fixed_48_refined_cost_measured' if cohort == 'V6'
                           else f"v{entry['version']}_gap_{entry['expected_queries']}_measured_twice")
        if (entry['version'] != int(cohort[1:]) or report['status'] != expected_status
                or read(entry['supervisor']) != report['supervisor']
                or not report['sources_reverified_before_after'] or report['T_plan'] is not None
                or report['scope']['full_readback_started'] is not False or report['scope']['reserved_test'] != 'locked'
                or len(report['repeats']) != entry['expected_repeats']
                or report['supervisor']['exit_code'] != 0 or report['supervisor']['stop_reason'] is not None
                or report['supervisor']['tracked_processes_alive_after_cleanup'] != 0
                or len(selection['probes']) != entry['expected_queries']):
            raise ValueError('Historical publication does not certify the requested bounded cohort')
        if [r['repeat_index'] for r in entry['repeats']] != list(range(entry['expected_repeats'])):
            raise ValueError('Missing or duplicate historical repeat')
        for probe in selection['probes']:
            identity = probe['key_sha256']
            if identity in wanted or _sha(probe['key']) != identity:
                raise ValueError('Duplicate or changed fixed identity across cohorts')
            wanted[identity] = (cohort, probe)
        selections[cohort], reports[cohort] = selection, report
    if len(wanted) != 156:
        raise ValueError('Expected 156 distinct comparable identities, excluding unmatched V3 observations')
    roster = manifest['roster']
    if bound.get(roster['path']) != roster:
        raise ValueError('Structural roster is not bound')
    thresholds = manifest['population']['p90_nearest_rank']
    original = selections['V6']['population']
    if (original['p90_nearest_rank'] != thresholds or original['roster_sha256'] != roster['sha256']
            or original['roster_bytes'] != roster['bytes'] or original['total_queries'] != 166897):
        raise ValueError('V17 structural definition differs from the original V6 population')
    populations, seen, cell_by_identity = Counter(), set(), {}
    digest = hashlib.sha256()
    count = length = 0
    with _path(root, roster).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            length += len(line)
            row = _decode(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or identity in seen or _sha(row['key']) != identity
                    or any(type(row[k]) is not int or row[k] < 0 for k in DIMENSIONS)):
                raise ValueError('Invalid structural roster identity, ordinal or workload')
            seen.add(identity)
            parent = ''.join('1' if row[k] > 0 and row[k] >= thresholds[k] else '0' for k in DIMENSIONS)
            cell = _cell(row, parent, 'neighbor_vote_grid')
            populations[cell] += 1
            if identity in wanted:
                cohort, probe = wanted[identity]
                if (any(probe[k] != row[k] for k in ('key', 'history_sha256', 'original_ordinal', *DIMENSIONS))
                        or probe['cell'] != (parent if cohort == 'V6' else cell)):
                    raise ValueError('Fixed sample differs from the frozen V6 structural classification')
                cell_by_identity[identity] = cell
            count += 1
    if (count != 166897 or length != roster['bytes'] or digest.hexdigest() != roster['sha256']
            or len(populations) != 55 or set(cell_by_identity) != set(wanted)):
        raise ValueError('Incomplete structural population or sample coverage')
    rows, overheads = [], []
    for entry in cohorts:
        cohort = entry['cohort']
        prior_proof = None
        for repeat in entry['repeats']:
            index = repeat['repeat_index']
            if repeat['proof_location'] != 'file':
                raise ValueError('Expected the saved standalone historical ledger proof')
            proof = read(repeat['proof'])
            if (proof != reports[cohort]['repeats'][index]['proof'] or proof['records'] != entry['expected_queries']
                    or not proof['checkpoint_chain_checked'] or (prior_proof is not None and proof != prior_proof)):
                raise ValueError('Saved ledger proof differs across repeats or from its public report')
            prior_proof = proof
            normalized = normalize_repeat(cohort, index, selections[cohort]['probes'],
                read(repeat['measurements']), read(repeat['observations']), cell_by_identity)
            rows.extend(normalized['rows'])
            overheads.append(normalized['overheads'])
    inventory_cells = manifest['cells']
    if len(inventory_cells) != 55 or len({r['cell'] for r in inventory_cells}) != 55 or len(rows) != 360:
        raise ValueError('Incomplete frozen cell inventory or observation count')
    for entry in inventory_cells:
        sample = [row for row in rows if row['cell'] == entry['cell']]
        by_cohort = {name: {'distinct_queries': len({r['key_sha256'] for r in sample if r['cohort'] == name}),
                            'observations': sum(r['cohort'] == name for r in sample)}
                     for name in COHORTS}
        if (entry['population'] != populations[entry['cell']]
                or entry['distinct_queries'] != len({r['key_sha256'] for r in sample})
                or entry['observations'] != len(sample) or entry['by_cohort'] != by_cohort):
            raise ValueError('Recomputed cell population or observation capacity differs from inventory')
    verify_bindings(root, records, watch)
    return {'populations': dict(populations), 'rows': rows, 'overheads': overheads, 'expected_cohorts': COHORTS}
