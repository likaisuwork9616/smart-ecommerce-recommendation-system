"""Pure G2 marginal rule candidate under the unchanged Stage 6 contract.

This module has no file access or real-data dispatcher.  It validates a complete
in-memory G0 dataset and requires the caller's explicit G1 acceptance assertion.
Source-byte provenance and authorization for any future real execution remain a
separate caller responsibility.  Individual assignments are private memory;
only ``aggregate`` is suitable for an aggregate-only publication path.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter

import numpy as np

from scripts import rfm_description as description

AXES = description.AXES
PERCENTAGES = (20, 40, 60, 80)


def _support_floor(n):
    """Frozen ceil(0.005*n) with the absolute minimum, without float rounding."""
    if type(n) is not int or n < 0:
        raise ValueError('Reference count must be a nonnegative integer')
    return max(100, (n + 199) // 200)


def _partition(rows):
    """Estimate the sole frozen candidate and assign these same active rows.

    The public entry validates schemas, state, ledger and domain first.  Keeping
    this helper independent of input row order makes the explicit original,
    reversed and PCG64 permutation comparisons exercise the actual algorithm.
    """
    n = len(rows)
    if not n:
        raise ValueError('Cannot estimate cutpoints for an empty reference')
    ids = [row['customer_unique_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Candidate requires unique customer IDs')
    floor = _support_floor(n)
    assignments = {
        identity: {'numeric_bins': {}, 'ordinals': {}, 'ordinal_tuple': []}
        for identity in ids
    }
    axes = {}
    for axis in AXES:
        values = sorted(row[axis] for row in rows)
        ranks = [(n * p + 99) // 100 for p in PERCENTAGES]
        raw_cuts = [values[rank - 1] for rank in ranks]
        distinct_cuts = sorted(set(raw_cuts))
        cuts = [cut for cut in distinct_cuts if cut < values[-1]]
        k = len(cuts) + 1
        counts = Counter()
        for row in rows:
            # bisect_left gives the first cut >= x: equality stays in the
            # lower numeric bin, using exact source integers throughout.
            numeric_bin = bisect_left(cuts, row[axis]) + 1
            ordinal = k + 1 - numeric_bin if axis == 'recency_seconds' else numeric_bin
            counts[numeric_bin] += 1
            assignment = assignments[row['customer_unique_id']]
            assignment['numeric_bins'][axis] = numeric_bin
            assignment['ordinals'][axis] = ordinal
            assignment['ordinal_tuple'].append(ordinal)
        bins = [
            {'numeric_bin': b,
             'ordinal': k + 1 - b if axis == 'recency_seconds' else b,
             'n': counts[b], 'meets_support_floor': counts[b] >= floor,
             'empty': counts[b] == 0}
            for b in range(1, k + 1)
        ]
        failures = []
        if not 2 <= k <= 5:
            failures.append('effective_levels_outside_2_to_5')
        if any(bin_row['empty'] for bin_row in bins):
            failures.append('empty_bin')
        if any(not bin_row['meets_support_floor'] for bin_row in bins):
            failures.append('insufficient_axis_bin_support')
        axes[axis] = {
            'n': n, 'percentages': list(PERCENTAGES),
            'quantile_ranks_1based': ranks, 'raw_cut_values': raw_cuts,
            'cut_values': cuts,
            'duplicate_cut_values_removed_n': len(raw_cuts) - len(distinct_cuts),
            'maximum_cut_values_removed_n': len(distinct_cuts) - len(cuts),
            'effective_levels': k, 'no_separation': k == 1,
            'bin_counts': bins, 'failed_checks': failures,
        }
    return {'axes': axes,
            'assignments_by_id': {identity: assignments[identity] for identity in sorted(ids)}}


def _check_ties(rows, candidate):
    """Reject any accidental same-value split, even if aggregate counts match."""
    assignments = candidate['assignments_by_id']
    ids = [row['customer_unique_id'] for row in rows]
    if set(assignments) != set(ids) or len(assignments) != len(rows):
        raise ValueError('Candidate assignments do not cover the exact same IDs')
    for axis in AXES:
        value_assignments = {}
        for row in rows:
            assignment = assignments[row['customer_unique_id']]
            observed = (assignment['numeric_bins'][axis], assignment['ordinals'][axis])
            previous = value_assignments.setdefault(row[axis], observed)
            if previous != observed:
                raise ValueError('Same-value ties split across candidate bins')


def _verify_reproducibility(rows, reference):
    """Require exact cuts and complete same-ID assignments in all three orders."""
    _check_ties(rows, reference)
    n = len(rows)
    permutation = np.random.Generator(np.random.PCG64(42)).permutation(n)
    variants = [('original', rows), ('reversed', list(reversed(rows))),
                ('pcg64_seed42', [rows[int(index)] for index in permutation])]
    results = []
    for name, variant_rows in variants:
        observed = reference if name == 'original' else _partition(variant_rows)
        _check_ties(variant_rows, observed)
        same_cuts = all(
            observed['axes'][axis] == reference['axes'][axis] for axis in AXES)
        same_assignments = observed['assignments_by_id'] == reference['assignments_by_id']
        if not same_cuts or not same_assignments:
            raise ValueError('Candidate cutpoints or same-ID assignments depend on row order')
        results.append({'name': name, 'reference_n': n,
                        'same_cutpoints_and_axis_summaries': same_cuts,
                        'same_ID_assignments': same_assignments,
                        'same_value_ties_unsplit': True})
    return {'status': 'passed', 'variants': results,
            'same_ID_assignments_100pct': True}


def evaluate_rule_candidate(dataset, evaluation_spec, *, expected_customer_ids, g1_accepted):
    """Return aggregate G2 eligibility and separate private in-memory assignments.

    ``g1_accepted=True`` asserts a prior review; it is not evidence of source
    provenance or permission for real execution.  This round calls this API only
    with synthetic datasets.  Data/roster/policy or reproducibility failures
    raise; inadequate levels/support retain the candidate with all failed checks.
    """
    if type(g1_accepted) is not bool or not g1_accepted:
        raise ValueError('Explicit accepted G1 review is required before a G2 candidate')
    if expected_customer_ids is None:
        raise ValueError('An independent complete customer ID roster is required')
    data = description._validate_and_order(dataset, evaluation_spec, expected_customer_ids)
    # Validate using the canonical full ledger, but exercise the candidate with
    # the actual input ordering rather than sorting away that check.
    rows = [row for row in dataset['customers'] if row['activity_state'] == 'active_complete']
    n = len(rows)
    floor = _support_floor(n)
    state_counts = Counter({state: 0 for state in data['summary']['customer_states']})
    state_counts.update(row['activity_state'] for row in data['customers'])
    common = {
        'format_version': 1,
        'candidate': 'frozen_marginal_P20_P40_P60_P80_rule',
        'reference_n': n, 'support_floor': floor,
        'routing_counts': {'population_n': len(data['customers']),
                           'by_state': dict(state_counts),
                           'complete_active_n': n,
                           'excluded_from_candidate_n': len(data['customers']) - n,
                           'same_ID_exhaustive_disjoint': True,
                           'independent_complete_roster_checked': True},
        'axes_and_units': {'recency_seconds': 'elapsed_seconds',
                           'frequency_orders': 'distinct_eligible_window_order_count',
                           'monetary_product_cents': 'nominal_BRL_product_gross_integer_cents'},
        'gate_status': {'G0': 'passed', 'G1': 'accepted_by_caller',
                        'G2': 'not_evaluable_empty_reference', 'G3': 'not_executed',
                        'temporal': 'pending_data'},
        'execution': {'source_RFM_modified': False, 'cutpoints_estimated': bool(n),
                      'ordinals_assigned_in_memory': bool(n),
                      'private_individual_files_written': False,
                      'clustering_models_executed': False,
                      'sensitivity_resampling_executed': False,
                      'model_fits': 0, 'dashboard': False},
        'limitations': [
            'This pure function does not verify source-byte provenance or authorize real execution.',
            'Only complete active customers enter cutpoint estimation and assignment; legal M=0 is retained.',
            'Ordinals describe this marginal rule only; no total value score, business names or actions.',
            'Small joint cells are individually unsupported and are never automatically merged.',
            'G2 does not establish G3 method sensitivity, temporal stability or business applicability.',
        ],
    }
    if not n:
        common['gate_status']['G1'] = 'not_evaluable_empty_reference'
        common.update(axes=dict.fromkeys(AXES), neutral_joint_cell_counts=[],
                      observed_joint_cells_n=0,
                      joint_partition_degeneracy={'degenerate': None, 'reason': 'empty_reference'},
                      failed_checks=[{'axis': None, 'check': 'empty_reference'}],
                      reproducibility={'status': 'not_evaluated_empty_reference', 'variants': [],
                                       'same_ID_assignments_100pct': None})
        return {'aggregate': common, 'assignments_by_id': {}}
    candidate = _partition(rows)
    reproducibility = _verify_reproducibility(rows, candidate)
    failures = [{'axis': axis, 'check': check} for axis in AXES
                for check in candidate['axes'][axis]['failed_checks']]
    assignments = candidate['assignments_by_id']
    cell_counts = Counter(tuple(item['ordinal_tuple']) for item in assignments.values())
    joint_cells = [
        {'ordinals': list(cell), 'n': count,
         'support_flag': 'insufficient_group_support' if count < floor else None}
        for cell, count in sorted(cell_counts.items())
    ]
    joint_degenerate = len(cell_counts) in (1, n)
    common['gate_status']['G2'] = 'ineligible' if failures else 'passed'
    common.update(axes=candidate['axes'], neutral_joint_cell_counts=joint_cells,
                  observed_joint_cells_n=len(cell_counts),
                  joint_partition_degeneracy={
                      'degenerate': joint_degenerate,
                      'reason': ('single_joint_group' if len(cell_counts) == 1 else
                                 'every_ID_singleton' if len(cell_counts) == n else None),
                      'G3_not_evaluated': True},
                  failed_checks=failures, reproducibility=reproducibility)
    return {'aggregate': common, 'assignments_by_id': assignments}
