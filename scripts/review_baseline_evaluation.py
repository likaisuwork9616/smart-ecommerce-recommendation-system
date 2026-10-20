"""Frozen baseline coverage/metric definitions; no fitting or feature building."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

CANDIDATES = (0.1, 1.0, 10.0)
TIE_TOLERANCE = 1e-12
STATES = ('known_low_1_2', 'known_other_3_5', 'immature_observation_window',
          'unpositionable_answer_source_quality', 'invalid_visible_review_quality',
          'ambiguous_first_answer_tie', 'first_answer_not_after_approval',
          'late_answer_unknown', 'no_visible_answer_at_cutoff')


def label_support(block):
    """Count usable labels without turning unknown targets into negatives."""
    if block.order_id.isna().any() or block.order_id.duplicated().any():
        raise ValueError('Evaluation roster IDs must be present and unique')
    if not block.role_label_usable.map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError('Usability must use actual boolean masks')
    usable = block.role_label_usable.astype(bool)
    if not block.label_state.isin(STATES).all():
        raise ValueError('Unknown label state')
    if not usable.eq(block.label_state.isin(STATES[:2])).all():
        raise ValueError('Label state and usability disagree')
    if block.loc[~usable, 'y'].notna().any() or block.loc[usable, 'y'].isna().any():
        raise ValueError('Unknown target must stay nullable; known labels must exist')
    y = pd.to_numeric(block.y, errors='coerce')
    if (not y.loc[usable].isin([0, 1]).all()
            or block.loc[usable, 'y'].map(lambda value: isinstance(value, (bool, np.bool_))).any()):
        raise ValueError('Known labels must be binary')
    if (not block.loc[y.eq(1).fillna(False), 'label_state'].eq(STATES[0]).all()
            or not block.loc[y.eq(0).fillna(False), 'label_state'].eq(STATES[1]).all()):
        raise ValueError('Known target class disagrees with its label state')
    states = {state: int(block.label_state.eq(state).sum()) for state in STATES}
    return {'full_orders': len(block), 'known_labels': int(usable.sum()),
            'unknown_or_ineligible_labels': int((~usable).sum()),
            'known_low_1_2': int(y.eq(1).sum()), 'known_other_3_5': int(y.eq(0).sum()),
            'exclusive_label_states': states}, usable, y


def require_both_classes(block):
    support, _, _ = label_support(block)
    if support['known_low_1_2'] == 0 or support['known_other_3_5'] == 0:
        raise ValueError('insufficient_support_stop_fold')
    return support


def constant_reference_probability(training_block):
    support = require_both_classes(training_block)
    return support['known_low_1_2'] / support['known_labels']


def evaluate_role(probabilities, block):
    support, usable, y = label_support(block)
    if (not isinstance(probabilities, pd.Series) or probabilities.index.has_duplicates
            or list(probabilities.index) != list(block.order_id)):
        raise ValueError('Scores must retain the full role roster in canonical order')
    p = probabilities.to_numpy(dtype='float64')
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('Every query probability must be finite and inside [0,1]')
    metrics = {'average_precision': None, 'roc_auc': None, 'brier': None, 'binary_log_loss': None,
               'TP': None, 'FP': None, 'TN': None, 'FN': None, 'precision': None, 'recall': None}
    if support['known_labels']:
        known_y = y.loc[usable].to_numpy(dtype='int64')
        known_p = p[usable.to_numpy()]
        if support['known_low_1_2'] and support['known_other_3_5']:
            metrics['average_precision'] = float(average_precision_score(known_y, known_p))
            metrics['roc_auc'] = float(roc_auc_score(known_y, known_p))
        metrics['brier'] = float(np.mean((known_p - known_y) ** 2))
        clipped = np.clip(known_p, 1e-15, 1 - 1e-15)
        metrics['binary_log_loss'] = float(np.mean(-known_y * np.log(clipped) - (1-known_y) * np.log(1-clipped)))
        predicted = known_p >= 0.5
        positive = known_y == 1
        metrics.update({'TP': int((predicted & positive).sum()), 'FP': int((predicted & ~positive).sum()),
                        'TN': int((~predicted & ~positive).sum()), 'FN': int((~predicted & positive).sum())})
        if metrics['TP'] + metrics['FP']:
            metrics['precision'] = metrics['TP'] / (metrics['TP'] + metrics['FP'])
        if metrics['TP'] + metrics['FN']:
            metrics['recall'] = metrics['TP'] / (metrics['TP'] + metrics['FN'])
    if any(value is not None and not np.isfinite(value) for value in metrics.values()):
        raise ValueError('Nonfinite metric stops the fold; no candidate can be removed')
    return {'coverage': support, 'metrics': metrics}


def select_candidate(candidate_average_precision):
    if (set(candidate_average_precision) != set(CANDIDATES)
            or any(isinstance(C, (bool, np.bool_)) for C in candidate_average_precision)):
        raise ValueError('All three frozen candidates are required')
    if any(value is None or isinstance(value, (bool, np.bool_)) or not np.isfinite(value)
           or not 0 <= value <= 1 for value in candidate_average_precision.values()):
        raise ValueError('Any failed or nonfinite candidate stops the complete fold')
    maximum = max(candidate_average_precision.values())
    eligible = [float(C) for C, value in candidate_average_precision.items() if maximum - value <= TIE_TOLERANCE]
    chosen = min(eligible)
    return {'selected_C': chosen, 'candidate_average_precision': [
                {'C': float(C), 'average_precision': float(candidate_average_precision[C])} for C in CANDIDATES],
            'maximum_average_precision': float(maximum), 'tie_absolute_tolerance': TIE_TOLERANCE,
            'candidates_within_tolerance': sorted(eligible), 'tie_break': 'smallest_C',
            'outer_labels_used': False, 'reference_in_selection': False}


def macro_average_precision(fold_evaluations):
    if len(fold_evaluations) != 3:
        raise ValueError('All three development months must be reported')
    values = [item['metrics']['average_precision'] for item in fold_evaluations]
    if any(value is not None and (not np.isfinite(value) or not 0 <= value <= 1) for value in values):
        raise ValueError('Invalid outer metric cannot be silently dropped')
    valid = [value for value in values if value is not None and np.isfinite(value)]
    return {'macro_average_precision': float(np.mean(valid)) if len(valid) == 3 else None,
            'valid_folds': len(valid), 'required_folds': 3, 'weighting': 'equal_month_weight',
            'pooled_average_precision_computed': False, 'independent_fold_confidence_interval': False}
