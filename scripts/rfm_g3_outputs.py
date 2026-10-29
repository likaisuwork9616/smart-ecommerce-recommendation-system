"""Independent rank, full-ID assignment and exact-contingency ARI readback."""
from collections import Counter
from fractions import Fraction
import math
from pathlib import Path
import uuid

import numpy as np

from scripts import rfm_g3 as core
from scripts import rfm_dataset_artifacts as typed
from scripts import audit_rfm_feasibility as base

FILES = ('aggregate.json', 'sampled_positions.json', 'assignments.csv', 'manifest.json')
require = core.require


def exact_ari(left, right):
    require(len(left) == len(right) and len(left) > 1, 'ARI requires aligned nonempty reference')
    choose2 = lambda n: n * (n - 1) // 2
    total = choose2(len(left))
    joint = sum(choose2(n) for n in Counter(zip(left, right)).values())
    a = sum(choose2(n) for n in Counter(left).values())
    b = sum(choose2(n) for n in Counter(right).values())
    denominator = total * (a + b) - 2 * a * b
    return Fraction(2 * (total * joint - a * b), denominator) if denominator else Fraction(1)


def _joint(values, floor):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    cells = [{'ordinals': list(k), 'n': counts[k],
              'support_flag': None if counts[k] >= floor else 'insufficient_group_support'}
             for k in sorted(counts)]
    return {'cells': cells, 'observed_cells': len(counts),
            'small_cells': len([v for v in counts.values() if v < floor]),
            'customers_in_small_cells': sum(v for v in counts.values() if v < floor),
            'degenerate': len(counts) == 1 or len(counts) == len(values)}


def _scalar_count(value):
    if isinstance(value, dict): return sum(_scalar_count(v) for v in value.values())
    if isinstance(value, list): return sum(_scalar_count(v) for v in value)
    return 1


def verify_result(rows, reference, evaluation, result):
    ids = core.validate_reference(rows, reference, evaluation)
    require(set(result) == {'aggregate', 'samples', 'assignments'}, 'Unexpected G3 result shape')
    n, sample_n, floor = len(ids), len(ids) * 4 // 5, max(100, math.ceil(Fraction(len(ids), 200)))
    # The strict serializer verifies exact scalar types and every private column.
    typed._csv_bytes(result['assignments'], core.SCHEMA)
    require(len(result['assignments']) == n * 5 and len(result['samples']) == 5,
            'All five full-reference ledgers are required')
    agg = result['aggregate']
    require(type(agg['runs']) is list and len(agg['runs']) == 5, 'Exactly five reported seeds required')
    ref_tuples = [tuple(reference['assignments_by_id'][i]['ordinal_tuple']) for i in ids]
    ref_joint = _joint(ref_tuples, floor)
    ref_failures = []
    ref_axes = reference['aggregate']['axes']
    for axis in core.AXES:
        if not 2 <= ref_axes[axis]['effective_levels'] <= 5 or any(b['n'] < floor for b in ref_axes[axis]['bin_counts']):
            ref_failures.append(axis + ':reference_levels_or_support')
    if ref_joint['degenerate']: ref_failures.append('reference_joint_degenerate')
    expected_runs = []
    for index, seed in enumerate(core.SEEDS):
        actual = agg['runs'][index]
        draws = np.random.Generator(np.random.PCG64(seed)).choice(n, size=sample_n, replace=False).tolist()
        require(typed._same(result['samples'][index], {'seed': seed, 'canonical_positions_in_draw_order': draws}),
                'Saved sample differs from the frozen PCG64 draw')
        sampled = set(draws)
        ledger = result['assignments'][index*n:(index+1)*n]
        require([r['customer_unique_id'] for r in ledger] == ids, 'Full canonical same-ID ledger required')
        expected_rows = [dict(customer_unique_id=i, seed=seed, sampled_for_cutpoints=j in sampled)
                         for j, i in enumerate(ids)]
        axes, failures = {}, []
        for axis, prefix in zip(core.AXES, core.PREFIXES):
            ordered = sorted(rows[position][axis] for position in draws)
            ranks = [math.ceil(Fraction(sample_n * p, 100)) for p in (20, 40, 60, 80)]
            raw = [ordered[k-1] for k in ranks]
            cuts = sorted({x for x in raw if x != ordered[-1]})
            k = 1 + len(cuts)
            bins = [1 + sum(row[axis] > cut for cut in cuts) for row in rows]
            ordinals = [k + 1 - b if prefix == 'r' else b for b in bins]
            counts = [sum(b == label for b in bins) for label in range(1, k+1)]
            comparable = k == ref_axes[axis]['effective_levels']
            dimension = core.AXES.index(axis)
            matches = sum(ordinal == ref[dimension] for ordinal, ref in zip(ordinals, ref_tuples)) if comparable else None
            if k < 2 or k > 5: failures.append(axis + ':levels_outside_2_to_5')
            if not comparable: failures.append(axis + ':levels_differ_from_reference')
            if 0 in counts: failures.append(axis + ':empty_bin')
            if min(counts) < floor: failures.append(axis + ':insufficient_axis_bin_support')
            if matches is not None and Fraction(matches, n) < Fraction(9, 10):
                failures.append(axis + ':agreement_below_0.90')
            axes[axis] = {'sample_n': sample_n, 'quantile_ranks_1based': ranks,
                'sample_min': ordered[0], 'sample_max': ordered[-1], 'raw_cut_values': raw,
                'cut_values': cuts, 'effective_levels': k, 'full_reference_bin_counts': counts,
                'agreement': {'comparable_levels': comparable, 'matched_customers': matches,
                              'reference_n': n, 'value': matches/n if comparable else None}}
            for row, b, ordinal in zip(expected_rows, bins, ordinals):
                row[prefix + '_numeric_bin'], row[prefix + '_ordinal'] = b, ordinal
        expected_rows = [{key: row[key] for key, _ in core.SCHEMA} for row in expected_rows]
        require(typed._same(ledger, expected_rows), 'Saved ID, sampling membership, bin or ordinal differs')
        tuples = [tuple(row[p + '_ordinal'] for p in core.PREFIXES) for row in expected_rows]
        joint = _joint(tuples, floor)
        exact = exact_ari(ref_tuples, tuples)
        require(type(actual['joint_ARI']) is float and math.isfinite(actual['joint_ARI'])
                and abs(actual['joint_ARI'] - float(exact)) <= 1e-12, 'ARI differs from exact contingency oracle')
        if exact < Fraction(4, 5): failures.append('joint_ARI_below_0.80')
        if joint['degenerate']: failures.append('joint_partition_degenerate')
        expected_runs.append({'seed': seed, 'sample_n': sample_n, 'reference_n': n, 'axes': axes,
            'joint_ARI': actual['joint_ARI'], 'joint': joint, 'failed_checks': failures,
            'gate': 'ineligible' if failures else 'passed'})
    minima = {}
    for axis in core.AXES:
        values = [r['axes'][axis]['agreement']['value'] for r in expected_runs]
        minima[axis] = None if None in values else min(values)
    expected = {'format_version': 1, 'reference_n': n, 'sample_n': sample_n, 'seeds': list(core.SEEDS),
        'support_floor': floor,
        'reference': {'levels': {a: ref_axes[a]['effective_levels'] for a in core.AXES},
                      'joint': ref_joint, 'failed_checks': ref_failures},
        'runs': expected_runs, 'minimum_axis_agreement': minima,
        'minimum_joint_ARI': min(r['joint_ARI'] for r in expected_runs),
        'gate_status': {'G3': 'passed' if not ref_failures and all(r['gate'] == 'passed' for r in expected_runs) else 'ineligible',
                        'temporal': 'pending_data', 'business': 'pending_data'},
        'execution': {'seeds_evaluated': 5, 'G2_core_calls': 0, 'model_fits': 0,
                      'source_RFM_modified': False, 'dashboard': False}, 'limitations': core.LIMITATIONS}
    require(typed._same(agg, expected), 'G3 aggregate, support, worst case or gate differs')
    return {'accepted': True, 'seeds_verified': 5, 'sample_positions_compared': sample_n * 5,
            'full_reference_assignment_rows': n * 5, 'assignment_cells_compared': n * 5 * len(core.SCHEMA),
            'aggregate_scalars_compared': _scalar_count(expected), 'exact_contingency_ARI_oracle': True,
            'G3_core_reexecuted': False, 'same_ID_membership_cuts_bins_ordinals_support_verified': True}


def bundle_guard(path):
    path = Path(path)
    require(path.is_dir() and {p.name for p in path.iterdir()} == set(FILES), 'Exact four-file G3 bundle required')
    require(not path.is_symlink() and all(not (path / name).is_symlink() for name in FILES), 'Symlink bundle rejected')
    return {name: typed._digest((path / name).read_bytes()) for name in FILES}


def read_bundle(path, provenance):
    path = Path(path)
    guard = bundle_guard(path)
    manifest = base.read_json(path / 'manifest.json')
    result = {'aggregate': base.read_json(path / 'aggregate.json'),
              'samples': base.read_json(path / 'sampled_positions.json'),
              'assignments': typed._read_csv(path / 'assignments.csv', core.SCHEMA)}
    expected = {'format_version': 1, 'provenance': provenance, 'schema': core.SCHEMA,
                'assignment_rows': len(result['assignments']),
                'private_files': {name: guard[name] for name in FILES[:3]}}
    require(typed._same(manifest, expected), 'G3 manifest, provenance or bytes differ')
    for name in ('aggregate.json', 'sampled_positions.json', 'manifest.json'):
        require((path / name).read_bytes() == typed.json_bytes(base.read_json(path / name)), 'Noncanonical G3 JSON')
    return result


def write_bundle(path, rows, reference, evaluation, result, provenance):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), 'Do not overwrite a G3 bundle')
    receipt = verify_result(rows, reference, evaluation, result)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + '.staging-' + uuid.uuid4().hex)
    staging.mkdir()
    payloads = {'aggregate.json': typed.json_bytes(result['aggregate']),
                'sampled_positions.json': typed.json_bytes(result['samples']),
                'assignments.csv': typed._csv_bytes(result['assignments'], core.SCHEMA)}
    payloads['manifest.json'] = typed.json_bytes({'format_version': 1, 'provenance': provenance,
        'schema': core.SCHEMA, 'assignment_rows': len(result['assignments']),
        'private_files': {name: typed._digest(data) for name, data in payloads.items()}})
    for name, data in payloads.items():
        with (staging / name).open('xb') as stream: stream.write(data)
    restored = read_bundle(staging, provenance)
    require(typed._same(restored, result), 'Full G3 persisted readback differs')
    staging.rename(path)
    return receipt
