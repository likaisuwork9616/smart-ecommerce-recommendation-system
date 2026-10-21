"""Read-only paired probability, ranking and one-feature support descriptions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import review_score_diagnostics as descriptive

FEATURES = ('purchase_dayofweek', 'purchase_hour', 'approval_wait_hours')


def diagnostic_protocol():
    return {
        'arms': ['treatment_three_features', 'control_four_features'],
        'difference': 'treatment_minus_control',
        'score_blocks': 'all_18_per_arm_exact_same_ID_order_truth',
        'inner_comparison': 'same_C_each_0.1_1_10_no_reselection',
        'outer_comparison': 'each_arm_existing_selected_C_may_differ',
        'probability_subsets': ['full', 'known', 'low', 'other', 'unknown'],
        'quantiles': list(descriptive.QUANTILES), 'quantile_method': 'linear',
        'rank': {'order': 'descending_probability',
                 'position_ties': 'original_canonical_role_order_stable_sort',
                 'spearman': 'Pearson_of_average_ranks_null_if_constant_or_under_two',
                 'position_shift': 'control_position_minus_treatment_position_positive_moves_up',
                 'subsets': ['full', 'known', 'unknown'],
                 'subsets_reranked_separately': True,
                 'tie_excess_rows': 'orders_minus_distinct_probability_values',
                 'alert_budget_or_top_k_selection': False},
        'features': list(FEATURES),
        'training_reference': 'own_fit_eligible_labels_only_same_for_both_arms',
        'categorical_vocabulary': {k: list(descriptive.CATEGORIES[k]) for k in FEATURES[:2]},
        'wait_bin_edges': [0, 1, 6, 24, 72, 168, 'positive_infinity'],
        'bin_closure': 'left_closed_right_open',
        'support_boundary': 30, 'support_boundary_for_description_only': True,
        'strata': 'one_feature_at_a_time_only_no_search_or_cross_feature_slices',
        'stratum_loss': 'Brier_and_clipped_logloss_delta_sum_divided_by_whole_role_known_count',
        'loss_epsilon': descriptive.LOG_EPSILON,
        'feature_strata_roles': 'outer_evaluation_selected_models_only',
        'empty_mean_rate_correlation': None,
        'empty_stratum_contribution': 'zero_if_whole_role_known_denominator_positive_else_null',
        'model_fit_transform_predict_calls': 0, 'candidate_selections': 0,
        'threshold_optimization': False, 'calibration': False,
        'new_unseen_holdout_or_performance_claim': False, 'dashboard': False,
    }


def ranking(control, treatment):
    """Describe vectors in canonical role order; return aggregates only."""
    control, treatment = np.asarray(control, dtype=float), np.asarray(treatment, dtype=float)
    if (control.ndim != 1 or treatment.shape != control.shape
            or not np.isfinite(control).all() or not np.isfinite(treatment).all()
            or ((control < 0) | (control > 1) | (treatment < 0) | (treatment > 1)).any()):
        raise ValueError('Ranking requires equal finite probability vectors')
    n = len(control)
    positions = []
    for values in (control, treatment):
        position = np.empty(n, dtype=int)
        position[np.argsort(-values, kind='stable')] = np.arange(1, n + 1)
        positions.append(position)
    shift = positions[0] - positions[1]
    average = [pd.Series(v).rank(method='average').to_numpy() for v in (control, treatment)]
    rho = (float(np.corrcoef(*average)[0, 1])
           if n > 1 and all(np.ptp(v) > 0 for v in average) else None)
    return {'orders': n, 'spearman_average_ranks': rho,
            'moved_up': int((shift > 0).sum()), 'moved_down': int((shift < 0).sum()),
            'unchanged_position': int((shift == 0).sum()),
            'absolute_position_change': descriptive._distribution(np.abs(shift)),
            'control_tie_excess_rows': int(n - len(np.unique(control))),
            'treatment_tie_excess_rows': int(n - len(np.unique(treatment)))}


def paired_profile(control, treatment, truth, *, include_ranking=True):
    ids, masks, _ = descriptive._labels(truth)
    c = descriptive._probabilities(control, ids)
    t = descriptive._probabilities(treatment, ids)
    delta = t - c
    result = {
        'control': descriptive.score_profile(control, truth),
        'treatment': descriptive.score_profile(treatment, truth),
        'probability_change': {key: {
            'signed': descriptive._distribution(delta[mask]),
            'absolute': descriptive._distribution(np.abs(delta[mask])),
            'increased': int((delta[mask] > 0).sum()),
            'decreased': int((delta[mask] < 0).sum()),
            'exactly_equal': int((delta[mask] == 0).sum())}
            for key, mask in masks.items()},
    }
    if include_ranking:
        result['ranking'] = {key: ranking(c[masks[key]], t[masks[key]])
                             for key in ('full', 'known', 'unknown')}
    return result


def feature_support(train_x, query_x, truth):
    result = descriptive.compare_feature_support(train_x, query_x, truth)
    del result['categorical']['purchase_month']
    return result


def feature_strata(train_x, query_x, truth, control, treatment):
    """Fixed outer strata; contribution sums reconstruct the existing loss delta."""
    descriptive._validate_features(train_x, 'Eligible training')
    descriptive._validate_features(query_x, 'Query')
    ids, masks, y = descriptive._labels(truth)
    if list(query_x.index) != ids:
        raise ValueError('Query feature order must match the role')
    c = descriptive._probabilities(control, ids)
    t = descriptive._probabilities(treatment, ids)
    known = masks['known']; denominator = int(known.sum())
    losses = [descriptive._losses(v[known], y[known]) for v in (c, t)]
    result = {}
    for feature in FEATURES:
        training, query = train_x[feature].to_numpy(), query_x[feature].to_numpy()
        if feature == 'approval_wait_hours':
            train_masks = descriptive._bin_masks(training, descriptive.WAIT_EDGES)
            query_masks = descriptive._bin_masks(query, descriptive.WAIT_EDGES)
            labels = [descriptive._bin_descriptor(i, descriptive.WAIT_EDGES) for i in range(len(query_masks))]
        else:
            categories = descriptive.CATEGORIES[feature]
            train_masks = [training == v for v in categories]
            query_masks = [query == v for v in categories]
            labels = [{'category': v} for v in categories]
        rows = []
        for label, tm, qm in zip(labels, train_masks, query_masks):
            local_known = qm & known
            n = int(local_known.sum())
            row = {**label, 'training_orders': int(tm.sum()),
                   'full_orders': int(qm.sum()), 'known_labels': n,
                   'unknown_labels': int((qm & ~known).sum()),
                   'known_low_1_2': int((qm & masks['low']).sum()),
                   'known_low_rate': descriptive._ratio(int((qm & masks['low']).sum()), n),
                   'control_full_probability_mean': float(c[qm].mean()) if qm.any() else None,
                   'treatment_full_probability_mean': float(t[qm].mean()) if qm.any() else None,
                   'known_probability_change_mean': float((t-c)[local_known].mean()) if n else None,
                   'loss_delta_contributions': {key: descriptive._ratio(
                       float((losses[1][key]-losses[0][key])[qm[known]].sum()), denominator)
                       for key in losses[0]}}
            rows.append(row)
        result[feature] = {'whole_role_known_denominator': denominator, 'strata': rows,
                           'summed_loss_delta_contributions': {key: descriptive._ratio(
                               float((losses[1][key]-losses[0][key]).sum()), denominator)
                               for key in losses[0]}}
    return result
