"""Bounded, aggregate diagnostics of existing scores and source event clocks.

This module has no model, file, or output writer dependency. It never fits a
preprocessor, creates predictions, chooses a candidate, or ranks orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


FEATURES = ('purchase_month', 'purchase_dayofweek', 'purchase_hour', 'approval_wait_hours')
CATEGORIES = {'purchase_month': tuple(range(1, 13)),
              'purchase_dayofweek': tuple(range(7)),
              'purchase_hour': tuple(range(24))}
QUANTILES = (0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0)
WAIT_EDGES = (0.0, 1.0, 6.0, 24.0, 72.0, 168.0, float('inf'))
SCORE_EDGES = (0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 1.0)
SUPPORT_BOUNDARY = 30
LOG_EPSILON = 1e-15
STATES = ('known_low_1_2', 'known_other_3_5', 'immature_observation_window',
          'unpositionable_answer_source_quality', 'invalid_visible_review_quality',
          'ambiguous_first_answer_tie', 'first_answer_not_after_approval',
          'late_answer_unknown', 'no_visible_answer_at_cutoff')


def diagnostic_protocol():
    """Return a fresh, JSON-safe record of every descriptive choice."""
    return {
        'features': list(FEATURES),
        'categorical_vocabulary': {key: list(value) for key, value in CATEGORIES.items()},
        'quantiles': list(QUANTILES), 'quantile_method': 'linear', 'standard_deviation_ddof': 0,
        'wait_hours_bin_edges': [0, 1, 6, 24, 72, 168, 'positive_infinity'],
        'score_bin_edges': list(SCORE_EDGES),
        'bin_closure': 'left_closed_right_open_last_score_bin_includes_one',
        'training_reference': 'own_fit_role_label_usable_only',
        'query_feature_subsets': ['full', 'known', 'unknown'],
        'score_distribution_subsets': ['full', 'known', 'low', 'other', 'unknown'],
        'low_rate_denominator': 'known_labels', 'unknown_rate_denominator': 'full_orders',
        'score_bias': 'known_probability_mean_minus_known_low_rate',
        'categorical_support': {'zero': 'train_count_equals_zero',
                                'sparse_positive': 'one_through_29_train_rows',
                                'below_30': 'includes_zero_and_sparse_positive',
                                'boundary': SUPPORT_BOUNDARY, 'purpose': 'description_only'},
        'total_variation': 'half_sum_absolute_proportion_difference_null_for_empty_population',
        'wait_support': ['strictly_below_train_min', 'strictly_above_train_max',
                         'outside_train_range', 'strictly_above_train_linear_p99'],
        'paired_loss': {'query_role': 'outer_evaluation', 'bins_defined_by': 'frozen_selected_logistic',
                        'comparison': 'same_order_frozen_constant_reference',
                        'contribution_denominator': 'all_known_labels_in_role',
                        'log_probability_clip_epsilon': LOG_EPSILON},
        'empty_statistics': None, 'fit_calls': 0, 'prediction_calls': 0,
        'candidate_reselection': False, 'new_ranking': False, 'threshold_optimization': False,
        'cross_feature_strata': False, 'infer_unknown_low_rate': False,
    }


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def _validate_ids(values, description):
    ids = list(values)
    if (any(not isinstance(value, str) or not value for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError(f'{description} IDs must be nonempty strings and unique')
    return ids


def _labels(block):
    required = ('order_id', 'role_label_usable', 'label_state', 'y')
    if (not isinstance(block, pd.DataFrame) or block.columns.has_duplicates
            or not set(required).issubset(block.columns)):
        raise ValueError('Role truth requires unique named label columns')
    ids = _validate_ids(block.order_id, 'Role')
    if not block.role_label_usable.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError('Role usability must contain actual booleans')
    known = block.role_label_usable.to_numpy(dtype=bool)
    if (not block.label_state.isin(STATES).all()
            or not np.array_equal(known, block.label_state.isin(STATES[:2]).to_numpy())):
        raise ValueError('Role label state and usability disagree')
    if block.y.iloc[np.flatnonzero(~known)].notna().any():
        raise ValueError('Unknown labels must remain null')
    known_y = block.y.iloc[np.flatnonzero(known)]
    if (known_y.isna().any()
            or known_y.map(lambda value: isinstance(value, (bool, np.bool_, str))).any()):
        raise ValueError('Known labels must be numeric binary values')
    numeric = pd.to_numeric(block.y, errors='coerce').to_numpy(dtype='float64', na_value=np.nan)
    if not np.isin(numeric[known], [0.0, 1.0]).all():
        raise ValueError('Known labels must be numeric binary values')
    low, other = known & (numeric == 1), known & (numeric == 0)
    if (not block.label_state.iloc[np.flatnonzero(low)].eq(STATES[0]).all()
            or not block.label_state.iloc[np.flatnonzero(other)].eq(STATES[1]).all()):
        raise ValueError('Known label and its state disagree')
    return ids, {'full': np.ones(len(block), dtype=bool), 'known': known,
                 'low': low, 'other': other, 'unknown': ~known}, numeric


def _coverage(masks):
    counts = {key: int(mask.sum()) for key, mask in masks.items()}
    return {'full_orders': counts['full'], 'known_labels': counts['known'],
            'unknown_or_ineligible_labels': counts['unknown'],
            'known_low_1_2': counts['low'], 'known_other_3_5': counts['other'],
            'known_label_rate': _ratio(counts['known'], counts['full']),
            'unknown_or_ineligible_rate': _ratio(counts['unknown'], counts['full']),
            'known_low_rate': _ratio(counts['low'], counts['known'])}


def _clock(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d %H:%M:%S')


def role_summary(block):
    """Describe one complete role; no global label substitution is allowed."""
    _, masks, _ = _labels(block)
    result = _coverage(masks)
    result['exclusive_label_states'] = {state: int(block.label_state.eq(state).sum()) for state in STATES}
    metadata = {}
    for name in ('outer_fold', 'role', 'fit_at', 'observation_cutoff'):
        if name in block:
            values = block[name].drop_duplicates()
            if len(values) > 1 or values.isna().any():
                raise ValueError(f'One role must have one non-null {name}')
            value = values.iloc[0] if len(values) else None
            metadata[name] = (_clock(value) if name.endswith('_at') or name.endswith('_cutoff')
                              else str(value)) if value is not None else None
    for name in ('prediction_time', 'window_deadline'):
        if name in block:
            if block[name].isna().any():
                raise ValueError(f'Role clock {name} must be present')
            metadata[name + '_minimum'] = _clock(block[name].min()) if len(block) else None
            metadata[name + '_maximum'] = _clock(block[name].max()) if len(block) else None
    if 'horizon_complete' in block:
        if not block.horizon_complete.map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise ValueError('Horizon completeness must contain actual booleans')
        metadata['horizon_complete_orders'] = int(block.horizon_complete.sum())
        metadata['horizon_incomplete_orders'] = int((~block.horizon_complete.astype(bool)).sum())
    result['metadata'] = metadata
    return result


def derive_clock_features(raw_orders, order_ids):
    """Read four descriptive values from original clocks, retaining requested order.

    This does not invoke the model builder or produce its 44-column design matrix.
    Invalid clocks outside the requested guarded roster are not reinterpreted.
    """
    required = ('order_id', 'order_purchase_timestamp', 'order_approved_at')
    if (not isinstance(raw_orders, pd.DataFrame) or raw_orders.columns.has_duplicates
            or not set(required).issubset(raw_orders.columns)):
        raise ValueError('Original order IDs and two event clocks are required')
    _validate_ids(raw_orders.order_id, 'Source')
    ids = _validate_ids(order_ids, 'Requested')
    indexed = raw_orders.loc[:, list(required)].set_index('order_id')
    if not set(ids).issubset(indexed.index):
        raise ValueError('Requested ID is absent from original clocks')
    selected = indexed.loc[ids]
    clocks = []
    for name in required[1:]:
        clock = pd.to_datetime(selected[name], format='%Y-%m-%d %H:%M:%S', errors='coerce')
        if not pd.api.types.is_datetime64_dtype(clock.dtype) or clock.isna().any():
            raise ValueError('Requested event clocks must be valid and timezone-naive')
        clocks.append(clock)
    purchase, approval = clocks
    wait = (approval - purchase).dt.total_seconds() / 3600
    features = pd.DataFrame({'purchase_month': purchase.dt.month,
                             'purchase_dayofweek': purchase.dt.dayofweek,
                             'purchase_hour': purchase.dt.hour,
                             'approval_wait_hours': wait}, index=selected.index).astype('float64')
    _validate_features(features, 'Derived clock')
    return features


def _validate_features(frame, description):
    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != FEATURES:
        raise ValueError(f'{description} must contain exactly the four ordered feature columns')
    _validate_ids(frame.index, description)
    if any(not pd.api.types.is_numeric_dtype(frame[name].dtype)
           or pd.api.types.is_bool_dtype(frame[name].dtype) for name in FEATURES):
        raise ValueError('Descriptive features must use numeric values')
    values = frame.to_numpy(dtype='float64', na_value=np.nan)
    if not np.isfinite(values).all():
        raise ValueError('Descriptive features must be finite')
    for name, vocabulary in CATEGORIES.items():
        if not frame[name].isin(vocabulary).all():
            raise ValueError(f'{name} must use the fixed calendar vocabulary')
    if frame.approval_wait_hours.lt(0).any():
        raise ValueError('Approval wait must be nonnegative')


def _distribution(values):
    values = np.asarray(values, dtype='float64')
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError('Distribution values must be a finite vector')
    quantile_values = np.quantile(values, QUANTILES, method='linear') if len(values) else [None] * len(QUANTILES)
    return {'orders': len(values), 'mean': float(np.mean(values)) if len(values) else None,
            'standard_deviation': float(np.std(values, ddof=0)) if len(values) else None,
            'minimum': float(np.min(values)) if len(values) else None,
            'maximum': float(np.max(values)) if len(values) else None,
            'quantiles': {f'{q:g}': float(value) if value is not None else None
                          for q, value in zip(QUANTILES, quantile_values)}}


def _bin_masks(values, edges):
    values = np.asarray(values, dtype='float64')
    return [(values >= lower) & ((values <= upper) if index == len(edges)-2 else (values < upper))
            for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:]))]


def _bin_descriptor(index, edges):
    lower, upper = edges[index], edges[index + 1]
    return {'lower': float(lower), 'upper': float(upper) if np.isfinite(upper) else None,
            'upper_unbounded': bool(np.isinf(upper)),
            'lower_inclusive': True, 'upper_inclusive': bool(index == len(edges)-2 and np.isfinite(upper))}


def _proportions(counts):
    total = sum(counts)
    return [float(count / total) if total else None for count in counts]


def _total_variation(first, second):
    if any(value is None for value in first + second):
        return None
    return float(np.abs(np.asarray(first) - np.asarray(second)).sum() / 2)


def _support_count(mask, denominator):
    count = int(np.asarray(mask).sum())
    return {'orders': count, 'fraction': _ratio(count, denominator)}


def compare_feature_support(training_features, query_features, query_block):
    """Compare own-fit eligible training rows with full/known/unknown query rows.

    The caller supplies only eligible training rows; the guarded runner establishes
    that lineage. No label from the query enters the training reference.
    """
    _validate_features(training_features, 'Eligible training')
    _validate_features(query_features, 'Query')
    ids, masks, _ = _labels(query_block)
    if list(query_features.index) != ids:
        raise ValueError('Query feature order must match complete role truth')
    subsets = {key: masks[key] for key in ('full', 'known', 'unknown')}
    result = {'eligible_training_orders': len(training_features),
              'query_orders': {key: int(mask.sum()) for key, mask in subsets.items()},
              'categorical': {}}
    for name, vocabulary in CATEGORIES.items():
        training = training_features[name].to_numpy()
        train_counts = [int((training == category).sum()) for category in vocabulary]
        train_proportions = _proportions(train_counts)
        rows = [{'category': int(category), 'training_orders': count,
                 'training_proportion': proportion}
                for category, count, proportion in zip(vocabulary, train_counts, train_proportions)]
        query_profiles = {}
        for key, mask in subsets.items():
            query = query_features[name].to_numpy()[mask]
            counts = [int((query == category).sum()) for category in vocabulary]
            proportions = _proportions(counts)
            lookup = dict(zip(vocabulary, train_counts))
            support = np.asarray([lookup[value] for value in query], dtype='int64')
            query_profiles[key] = {
                'orders': len(query), 'counts': counts, 'proportions': proportions,
                'total_variation_from_training': _total_variation(train_proportions, proportions),
                'zero_training_support': _support_count(support == 0, len(query)),
                'sparse_positive_training_support': _support_count((support > 0) & (support < SUPPORT_BOUNDARY), len(query)),
                'below_30_training_support_including_zero': _support_count(support < SUPPORT_BOUNDARY, len(query)),
            }
        result['categorical'][name] = {'training_categories': rows, 'query_subsets': query_profiles}
    train_wait = training_features.approval_wait_hours.to_numpy(dtype='float64')
    train_wait_counts = [int(mask.sum()) for mask in _bin_masks(train_wait, WAIT_EDGES)]
    train_wait_proportions = _proportions(train_wait_counts)
    wait = {'training_distribution': _distribution(train_wait),
            'training_bins': [{**_bin_descriptor(index, WAIT_EDGES), 'orders': count,
                               'proportion': proportion}
                              for index, (count, proportion) in enumerate(zip(train_wait_counts, train_wait_proportions))],
            'query_subsets': {}}
    for key, mask in subsets.items():
        query = query_features.approval_wait_hours.to_numpy(dtype='float64')[mask]
        counts = [int(bin_mask.sum()) for bin_mask in _bin_masks(query, WAIT_EDGES)]
        proportions = _proportions(counts)
        support = {}
        if len(train_wait):
            below = query < np.min(train_wait)
            above = query > np.max(train_wait)
            supports = {'below_training_minimum': below, 'above_training_maximum': above,
                        'outside_training_range': below | above,
                        'above_training_p99': query > np.quantile(train_wait, 0.99, method='linear')}
            support = {name: _support_count(value, len(query)) for name, value in supports.items()}
        else:
            support = {name: {'orders': None, 'fraction': None} for name in
                       ('below_training_minimum', 'above_training_maximum', 'outside_training_range', 'above_training_p99')}
        wait['query_subsets'][key] = {'distribution': _distribution(query),
                                       'bin_counts': counts, 'bin_proportions': proportions,
                                       'bin_total_variation_from_training': _total_variation(train_wait_proportions, proportions),
                                       **support}
    result['approval_wait_hours'] = wait
    return result


def _probabilities(probabilities, ids):
    if (not isinstance(probabilities, pd.Series) or probabilities.index.has_duplicates
            or list(probabilities.index) != ids):
        raise ValueError('Frozen probabilities must retain the complete role ID order')
    if (not pd.api.types.is_numeric_dtype(probabilities.dtype)
            or pd.api.types.is_bool_dtype(probabilities.dtype)):
        raise ValueError('Frozen probabilities must use numeric values')
    values = probabilities.to_numpy(dtype='float64', na_value=np.nan)
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Frozen probabilities must be finite and inside [0,1]')
    return values


def score_profile(probabilities, query_block):
    """Describe one frozen score vector; its bins are not performance strata."""
    ids, masks, _ = _labels(query_block)
    values = _probabilities(probabilities, ids)
    coverage = _coverage(masks)
    distributions = {key: _distribution(values[mask]) for key, mask in masks.items()}
    known_mean = distributions['known']['mean']
    bias = known_mean - coverage['known_low_rate'] if known_mean is not None else None
    bins = []
    for index, bin_mask in enumerate(_bin_masks(values, SCORE_EDGES)):
        local_masks = {key: value & bin_mask for key, value in masks.items()}
        bins.append({**_bin_descriptor(index, SCORE_EDGES), **_coverage(local_masks),
                     'full_probability_mean': float(values[bin_mask].mean()) if bin_mask.any() else None,
                     'known_probability_mean': float(values[local_masks['known']].mean()) if local_masks['known'].any() else None})
    return {'coverage': coverage, 'distributions': distributions,
            'known_probability_bias': bias, 'score_bins': bins}


def _losses(probabilities, labels):
    clipped = np.clip(probabilities, LOG_EPSILON, 1 - LOG_EPSILON)
    return {'brier': (probabilities - labels) ** 2,
            'binary_log_loss': -labels * np.log(clipped) - (1-labels) * np.log(1-clipped)}


def paired_loss_profile(selected_probabilities, reference_probabilities, query_block):
    """Decompose existing outer losses in bins of the same selected score vector.

    All contributions divide by the complete role's known-label count. Empty bins
    contribute zero when that denominator exists; a wholly unknown role is null.
    """
    ids, masks, labels = _labels(query_block)
    if 'role' in query_block and not query_block.role.eq('outer_evaluation').all():
        raise ValueError('Paired loss decomposition is limited to outer evaluation')
    selected = _probabilities(selected_probabilities, ids)
    reference = _probabilities(reference_probabilities, ids)
    known = masks['known']
    denominator = int(known.sum())
    selected_loss = _losses(selected[known], labels[known])
    reference_loss = _losses(reference[known], labels[known])
    bins = []
    for index, bin_mask in enumerate(_bin_masks(selected, SCORE_EDGES)):
        within_known = bin_mask[known]
        local = {'known_labels': int(within_known.sum()), 'losses': {}}
        for metric in selected_loss:
            selected_sum = float(selected_loss[metric][within_known].sum())
            reference_sum = float(reference_loss[metric][within_known].sum())
            local['losses'][metric] = {
                'selected_sum': selected_sum, 'reference_sum': reference_sum,
                'selected_contribution': _ratio(selected_sum, denominator),
                'reference_contribution': _ratio(reference_sum, denominator),
                'selected_minus_reference_contribution': _ratio(selected_sum-reference_sum, denominator)}
        bins.append({**_bin_descriptor(index, SCORE_EDGES), **local})
    totals = {metric: {'selected': _ratio(float(selected_loss[metric].sum()), denominator),
                       'reference': _ratio(float(reference_loss[metric].sum()), denominator),
                       'selected_minus_reference': _ratio(float(selected_loss[metric].sum()-reference_loss[metric].sum()), denominator)}
              for metric in selected_loss}
    return {'binning_score': 'frozen_selected_logistic', 'contribution_denominator_known_labels': denominator,
            'score_bins': bins, 'totals_reconciled_to_existing_losses': totals}
