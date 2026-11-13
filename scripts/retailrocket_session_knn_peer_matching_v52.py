"""Select anonymous workload peers using predeclared exact numeric rules.

Only V51's pure schema/statistics helper is imported. No timing values, raw
files, SQL, workers or experiment runners are accepted or executed here.
"""
from fractions import Fraction
from math import isfinite

from scripts.retailrocket_session_knn_workload_distribution_v51 import summarize_workloads


MATCH_FIELDS = (
    'history_rows_inserted',
    'sql_overlap_membership_matches',
    'neighbor_pool_rows_hashed',
    'distinct_neighbor_similarities',
    'sql_vote_membership_rows_returned',
    'positive_causal_candidates',
)
REQUIRED_EQUAL_FIELDS = ('sql_selected_rows_inserted', 'fraction_fallback')
DIAGNOSTIC_FIELDS = ('vote_scale_bits', 'causal_catalog_candidates')
PRIMARY_MAX_FOLD = Fraction(5, 4)
EXPANDED_MAX_FOLD = Fraction(3, 2)


def _fold(left, right):
    if left == 0 and right == 0:
        return Fraction(1)
    if left == 0 or right == 0:
        return None
    return Fraction(max(left, right), min(left, right))


def _record(value):
    if value is None:
        return None
    try:
        display = float(value)
    except OverflowError:
        display = None
    if display is not None and not isfinite(display):
        display = None
    return dict(numerator=value.numerator, denominator=value.denominator, value=display)


def _diagnostics(target, peer):
    result = {}
    for name in DIAGNOSTIC_FIELDS:
        sentinel = name == 'vote_scale_bits' and target['fraction_fallback']
        if sentinel:
            fold = ratio = None
            fold_reason = ratio_reason = 'fraction_fallback is true; zero bit width is a fallback sentinel'
        else:
            fold = _fold(target[name], peer[name])
            ratio = Fraction(target[name], peer[name]) if peer[name] else None
            fold_reason = 'One side is zero, so a symmetric fold is undefined' if fold is None else None
            ratio_reason = 'Peer value is zero, so the target-to-peer ratio is undefined' if ratio is None else None
        result[name] = dict(fold=_record(fold), target_to_peer_ratio=_record(ratio),
            not_used_for_selection=True, fold_unavailable_reason=fold_reason,
            ratio_unavailable_reason=ratio_reason)
    return result


def select_workload_peers(workloads, targets=(32, 38)):
    """Return all exact-caliper matches and all tied nearest eligible records.

    Both target ordinals are excluded from each 46-record candidate set. A peer
    must first match the selected-row count and fallback flag exactly, then all
    six symmetric folds must be defined. Zero/zero gives a fold of one; a
    one-sided zero excludes that candidate. Every distance and threshold test
    uses Fraction, including nearest ties. Float ``value`` fields are display
    values only; numerator and denominator preserve the exact rational.

    ``condition_matched_count`` counts equal-condition candidates, while
    ``eligible_count`` additionally requires all six comparable folds. Profiles
    contain only the union of the 5/4 matches, 3/2 matches and nearest records.
    Nearest records outside a threshold are descriptive and never become peers
    within that threshold. Diagnostic fields never influence selection.
    """
    try:
        workloads = list(workloads)
    except TypeError as error:
        raise ValueError('Exactly 48 workload dictionaries are required') from error
    validation = summarize_workloads(workloads, targets=targets)
    targets = tuple(validation['target_ordinals'])
    positions = [position for position in range(1, 49) if position not in targets]
    results = {}
    for ordinal in targets:
        target = workloads[ordinal - 1]
        comparable = []
        condition_matched = 0
        one_sided_zero = 0
        for position in positions:
            peer = workloads[position - 1]
            if any(target[name] != peer[name] for name in REQUIRED_EQUAL_FIELDS):
                continue
            condition_matched += 1
            folds = {name: _fold(target[name], peer[name]) for name in MATCH_FIELDS}
            if any(value is None for value in folds.values()):
                one_sided_zero += 1
                continue
            comparable.append((position, max(folds.values()), folds))
        nearest = min((distance for _, distance, _ in comparable), default=None)
        primary = [position for position, distance, _ in comparable if distance <= PRIMARY_MAX_FOLD]
        expanded = [position for position, distance, _ in comparable if distance <= EXPANDED_MAX_FOLD]
        nearest_positions = [position for position, distance, _ in comparable if distance == nearest]
        keep = set(primary) | set(expanded) | set(nearest_positions)
        profiles = [dict(position=position, max_fold=_record(distance),
            folds={name: _record(value) for name, value in folds.items()},
            within_primary=distance <= PRIMARY_MAX_FOLD, within_expanded=distance <= EXPANDED_MAX_FOLD,
            diagnostics=_diagnostics(target, workloads[position - 1]))
            for position, distance, folds in comparable if position in keep]
        reason = None
        if nearest is None:
            reason = ('No candidate satisfies both required equal conditions' if not condition_matched
                      else 'No condition-matched candidate has comparable folds for all six fields')
        results[str(ordinal)] = dict(primary_positions=primary, expanded_positions=expanded,
            nearest_positions=nearest_positions, nearest_max_fold=_record(nearest),
            nearest_unavailable_reason=reason, candidates=len(positions),
            condition_matched_count=condition_matched, eligible_count=len(comparable),
            one_sided_zero_count=one_sided_zero, profiles=profiles)
    return dict(count=48, target_ordinals=list(targets), required_equal_fields=list(REQUIRED_EQUAL_FIELDS),
        matching_fields=list(MATCH_FIELDS), diagnostic_fields=list(DIAGNOSTIC_FIELDS),
        primary_max_fold=_record(PRIMARY_MAX_FOLD), expanded_max_fold=_record(EXPANDED_MAX_FOLD),
        targets=results,
        distance_method='Maximum of six exact Fraction symmetric folds; no summed or timing-based distance',
        zero_policy='0/0 fold is 1; one-sided zero excludes the candidate from all matching and nearest sets',
        nearest_policy='All eligible minimum-distance ties are retained; nearest does not relax either threshold',
        interpretation='Profiles use anonymous one-based positions and relative numeric folds only. '
                       'Similar selection fields do not control diagnostic fields or establish equal elapsed cost.')
