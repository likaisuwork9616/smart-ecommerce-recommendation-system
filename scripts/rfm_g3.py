"""Frozen five-seed RFM sensitivity on the same complete active reference."""
from bisect import bisect_left
from collections import Counter

import numpy as np
from sklearn.metrics import adjusted_rand_score

from scripts import rfm_evaluation_contract as method
from scripts import rfm_dataset_artifacts as typed

AXES = ('recency_seconds', 'frequency_orders', 'monetary_product_cents')
SEEDS = (11, 29, 42, 73, 101)
PREFIXES = ('r', 'f', 'm')
SCHEMA = [['customer_unique_id', 'nonempty_string'], ['seed', 'nonnegative_int64'],
          ['sampled_for_cutpoints', 'bool'],
          *[[p + '_numeric_bin', 'nonnegative_int64'] for p in PREFIXES],
          *[[p + '_ordinal', 'nonnegative_int64'] for p in PREFIXES]]
LIMITATIONS = [
    'Same snapshot sensitivity only; five resamples are not new time periods or a confidence interval.',
    'Small joint cells remain insufficient_group_support even when the global G3 gate passes.',
    'No automatic merging, commercial group naming, future value or business effect claim.',
    'Temporal and operational validation remain pending_data; no model training or Dashboard.',
]


def require(condition, message):
    if condition is not True:
        raise ValueError(message)


def validate_reference(rows, reference, evaluation):
    require(typed._same(evaluation.get('policy'), method.policy())
            and typed._same(evaluation.get('planned_outputs'), method.planned_outputs()), 'Frozen evaluation differs')
    ids = [r['customer_unique_id'] for r in rows]
    require(bool(ids) and ids == sorted(set(ids)) and all(type(i) is str and i == i.strip() and i for i in ids),
            'Full active reference must have canonical unique IDs')
    require(ids == sorted(reference['assignments_by_id'])
            and len(ids) == reference['aggregate']['reference_n']
            and reference['aggregate']['gate_status']['G2'] == 'passed', 'Accepted G2 complete reference required')
    for row in rows:
        require(row['activity_state'] == 'active_complete', 'Only complete active reference is permitted')
        require(all(type(row[a]) is int for a in AXES)
                and 0 < row[AXES[0]] <= 365 * 86400 and row[AXES[1]] >= 1
                and 0 <= row[AXES[2]] <= 2**63 - 1, 'Invalid raw RFM domain or type')
        expected = reference['assignments_by_id'][row['customer_unique_id']]
        for axis in AXES:
            cuts = reference['aggregate']['axes'][axis]['cut_values']
            b = bisect_left(cuts, row[axis]) + 1
            o = len(cuts) + 2 - b if axis == AXES[0] else b
            require(expected['numeric_bins'][axis] == b and expected['ordinals'][axis] == o,
                    'Frozen G2 assignment differs from reference value')
        require(expected['ordinal_tuple'] == [expected['ordinals'][a] for a in AXES], 'Frozen tuple differs')
    return ids


def joint_statistics(tuples, floor):
    counts = Counter(tuples)
    cells = [{'ordinals': list(key), 'n': n,
              'support_flag': 'insufficient_group_support' if n < floor else None}
             for key, n in sorted(counts.items())]
    return {'cells': cells, 'observed_cells': len(cells),
            'small_cells': sum(c['n'] < floor for c in cells),
            'customers_in_small_cells': sum(c['n'] for c in cells if c['n'] < floor),
            'degenerate': len(cells) in (1, len(tuples))}


def labels(tuples):
    mapping = {value: i for i, value in enumerate(sorted(set(tuples)))}
    return [mapping[v] for v in tuples]


def evaluate(rows, reference, evaluation):
    ids = validate_reference(rows, reference, evaluation)
    n = len(rows)
    sample_n, floor = (4 * n) // 5, max(100, (n + 199) // 200)
    require(sample_n > 0, 'Empty subsample is not evaluable')
    ref = reference['aggregate']
    ref_tuples = [tuple(reference['assignments_by_id'][i]['ordinal_tuple']) for i in ids]
    ref_joint = joint_statistics(ref_tuples, floor)
    reference_failures = []
    for axis in AXES:
        info = ref['axes'][axis]
        counts = Counter(reference['assignments_by_id'][i]['numeric_bins'][axis] for i in ids)
        require([counts[b] for b in range(1, info['effective_levels'] + 1)]
                == [b['n'] for b in info['bin_counts']], 'Frozen reference bin count differs')
        if not 2 <= info['effective_levels'] <= 5 or any(c < floor for c in counts.values()):
            reference_failures.append(axis + ':reference_levels_or_support')
    require(ref_joint['cells'] == ref['neutral_joint_cell_counts'], 'Frozen reference joint cells differ')
    if ref_joint['degenerate']:
        reference_failures.append('reference_joint_degenerate')
    runs, samples, ledger = [], [], []
    ref_labels = labels(ref_tuples)
    for seed in SEEDS:
        positions = np.random.Generator(np.random.PCG64(seed)).choice(n, size=sample_n, replace=False)
        selected = [int(p) for p in positions]
        sampled = set(selected)
        samples.append({'seed': seed, 'canonical_positions_in_draw_order': selected})
        run_rows = [dict(customer_unique_id=i, seed=seed, sampled_for_cutpoints=j in sampled)
                    for j, i in enumerate(ids)]
        axes, failures = {}, []
        for axis, prefix in zip(AXES, PREFIXES):
            values = sorted(rows[p][axis] for p in selected)
            ranks = [(sample_n * p + 99) // 100 for p in (20, 40, 60, 80)]
            raw = [values[p - 1] for p in ranks]
            cuts = [v for v in sorted(set(raw)) if v < values[-1]]
            levels = len(cuts) + 1
            bins = [bisect_left(cuts, r[axis]) + 1 for r in rows]
            ordinals = [levels + 1 - b if axis == AXES[0] else b for b in bins]
            counts = [bins.count(b) for b in range(1, levels + 1)]
            comparable = levels == ref['axes'][axis]['effective_levels']
            matches = sum(o == reference['assignments_by_id'][i]['ordinals'][axis]
                          for i, o in zip(ids, ordinals)) if comparable else None
            if not 2 <= levels <= 5: failures.append(axis + ':levels_outside_2_to_5')
            if not comparable: failures.append(axis + ':levels_differ_from_reference')
            if any(c == 0 for c in counts): failures.append(axis + ':empty_bin')
            if any(c < floor for c in counts): failures.append(axis + ':insufficient_axis_bin_support')
            if matches is not None and 10 * matches < 9 * n: failures.append(axis + ':agreement_below_0.90')
            axes[axis] = {'sample_n': sample_n, 'quantile_ranks_1based': ranks,
                'sample_min': values[0], 'sample_max': values[-1], 'raw_cut_values': raw,
                'cut_values': cuts, 'effective_levels': levels, 'full_reference_bin_counts': counts,
                'agreement': {'comparable_levels': comparable, 'matched_customers': matches,
                              'reference_n': n, 'value': matches / n if matches is not None else None}}
            for row, b, o in zip(run_rows, bins, ordinals):
                row[prefix + '_numeric_bin'], row[prefix + '_ordinal'] = b, o
        tuples = [tuple(row[p + '_ordinal'] for p in PREFIXES) for row in run_rows]
        joint = joint_statistics(tuples, floor)
        ari = float(adjusted_rand_score(ref_labels, labels(tuples)))
        if ari < 0.80: failures.append('joint_ARI_below_0.80')
        if joint['degenerate']: failures.append('joint_partition_degenerate')
        runs.append({'seed': seed, 'sample_n': sample_n, 'reference_n': n, 'axes': axes,
                     'joint_ARI': ari, 'joint': joint, 'failed_checks': failures,
                     'gate': 'ineligible' if failures else 'passed'})
        ledger.extend({k: row[k] for k, _ in SCHEMA} for row in run_rows)
    minima = {}
    for axis in AXES:
        values = [run['axes'][axis]['agreement']['value'] for run in runs]
        minima[axis] = min(values) if all(v is not None for v in values) else None
    aggregate = {'format_version': 1, 'reference_n': n, 'sample_n': sample_n,
        'seeds': list(SEEDS), 'support_floor': floor,
        'reference': {'levels': {a: ref['axes'][a]['effective_levels'] for a in AXES},
                      'joint': ref_joint, 'failed_checks': reference_failures},
        'runs': runs, 'minimum_axis_agreement': minima,
        'minimum_joint_ARI': min(r['joint_ARI'] for r in runs),
        'gate_status': {'G3': 'passed' if not reference_failures and all(r['gate'] == 'passed' for r in runs) else 'ineligible',
                        'temporal': 'pending_data', 'business': 'pending_data'},
        'execution': {'seeds_evaluated': 5, 'G2_core_calls': 0, 'model_fits': 0,
                      'source_RFM_modified': False, 'dashboard': False}, 'limitations': LIMITATIONS}
    return {'aggregate': aggregate, 'samples': samples, 'assignments': ledger}
