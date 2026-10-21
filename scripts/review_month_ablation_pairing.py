"""Full-roster frozen-score and future paired-output gates; never fit or score."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import freeze_review_dataset as dataset
from scripts import review_baseline_evaluation as labels
from scripts.run_review_baseline import FOLDS, SCORE_COLUMNS

CANDIDATES = (0.1, 1.0, 10.0)
ROLES = ('inner_validation', 'outer_evaluation')


def pairing_contract():
    """Policy only: future treatment still needs its own inner selection."""
    return {
        'control': 'existing_frozen_four_feature_scores_no_refit_or_reselection',
        'treatment': 'drop_purchase_month_only_independent_original_inner_AP_selection',
        'key': ['outer_fold', 'role', 'order_id'],
        'comparison_unit': 'complete_query_role_including_unknown',
        'metadata_columns': list(dataset.MEMBERSHIP_COLUMNS),
        'score_columns': list(SCORE_COLUMNS),
        'canonical_order': 'exact_frozen_role_order_no_join_sort_or_filter_repair',
        'inner_pairing': 'each_same_C_candidate_and_unchanged_constant_reference',
        'outer_pairing': 'each_arm_selected_C_may_differ_and_unchanged_constant_reference',
        'unknown_labels': 'nullable_never_fill_zero_keep_every_query_score',
        'probabilities': 'every_row_finite_binary64_in_closed_zero_one',
        'constant_reference': 'same_unsmoothed_eligible_training_low_fraction',
        'paired_metric_null_policy': 'difference_null_if_either_arm_null_never_fill_zero',
        'paired_macro_support': 'both_arms_all_three_months_valid_or_null',
        'selection_or_metrics_computed_by_this_gate': False,
        'source_version_requirement': 'caller_must_pass_one_verified_immutable_source_bundle',
        'stop_on_mismatch': True,
    }


def _candidate(value):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number))
            or value not in CANDIDATES):
        raise ValueError('C must be one frozen numeric candidate')
    return float(value)


def _truth(block):
    if (not isinstance(block, pd.DataFrame) or list(block.columns) != list(dataset.MEMBERSHIP_COLUMNS)
            or block.empty or block.order_id.isna().any() or block.order_id.duplicated().any()
            or not block.order_id.map(lambda value: isinstance(value, str) and bool(value)).all()):
        raise ValueError('Expected a nonempty full role with unique string IDs and exact metadata schema')
    for name in ('horizon_complete', 'role_label_usable'):
        if not block[name].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise ValueError('Role masks must be actual booleans')
    if (block.outer_fold.nunique(dropna=False) != 1 or block.role.nunique(dropna=False) != 1
            or block.outer_fold.iloc[0] not in FOLDS or block.role.iloc[0] not in ROLES):
        raise ValueError('Expected one frozen query role and fold')
    support, _, _ = labels.label_support(block)
    return support


def _schema(frame):
    if (not isinstance(frame, pd.DataFrame) or list(frame.columns) != list(SCORE_COLUMNS)
            or frame.empty or frame.index.has_duplicates):
        raise ValueError('Expected exact nonempty score schema and unique row index')


def validate_score_block(frame, truth, model, C, *, prior=None):
    """Validate stored values against role truth without computing performance."""
    _schema(frame)
    support = _truth(truth)
    actual_metadata = frame.loc[:, list(dataset.MEMBERSHIP_COLUMNS)]
    _truth(actual_metadata)
    if len(frame) != len(truth) or not frame.model.eq(model).all():
        raise ValueError('Score model or full-role denominator differs')
    expected_role = truth.role.iloc[0]
    permitted = ('constant_reference', 'logistic_candidate' if expected_role == 'inner_validation' else 'logistic_selected')
    if model not in permitted:
        raise ValueError('Model does not belong to the query role')
    if model == 'constant_reference':
        if C is not None or not frame.C.isna().all() or prior is None:
            raise ValueError('Constant reference requires null C and the eligible training prior')
    else:
        _candidate(C)
        if (frame.C.isna().any() or frame.C.map(lambda value: isinstance(value, (bool, np.bool_))).any()
                or not frame.C.eq(C).all()):
            raise ValueError('Selected or candidate C differs from its frozen identity')
    try:
        pd.testing.assert_frame_equal(actual_metadata.reset_index(drop=True), truth.reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError('Score metadata or canonical full roster differs') from exc
    if frame.probability_low_1_2.dtype != np.dtype('float64'):
        raise ValueError('Stored probabilities must have float64 dtype')
    probabilities = frame.probability_low_1_2.to_numpy()
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError('Every query probability, including unknown labels, must be finite in [0,1]')
    if prior is not None:
        if (isinstance(prior, (bool, np.bool_)) or not np.isfinite(prior) or not 0 <= prior <= 1
                or not np.equal(probabilities, prior).all()):
            raise ValueError('Constant probabilities differ from eligible training prevalence')
    return {'full_orders': support['full_orders'], 'known_labels': support['known_labels'],
            'unknown_or_ineligible_labels': support['unknown_or_ineligible_labels']}


def _report_folds(report):
    folds = report['results']['outer_folds']
    if (not isinstance(folds, list) or [fold['outer_fold'] for fold in folds] != list(FOLDS)):
        raise ValueError('Control report must retain all three frozen folds in order')
    for fold in folds:
        _candidate(fold['selection']['selected_C'])
        candidates = [item['C'] for item in fold['inner_candidates']]
        if candidates != list(CANDIDATES):
            raise ValueError('Control report must retain all three candidates in order')
        for C in candidates:
            _candidate(C)
    return folds


def _prior(bundle, fold, role):
    train_role = 'inner_train_pool' if role == 'inner_validation' else 'outer_train_pool'
    support = labels.require_both_classes(bundle.role_block(fold, train_role))
    return support['known_low_1_2'] / support['known_labels']


def _plans(role, selected_C):
    if role == 'inner_validation':
        return [('constant_reference', None)] + [('logistic_candidate', C) for C in CANDIDATES]
    return [('constant_reference', None), ('logistic_selected', _candidate(selected_C))]


def _select(frame, fold, role, model, C):
    mask = frame.outer_fold.eq(fold) & frame.role.eq(role) & frame.model.eq(model)
    mask &= frame.C.isna() if C is None else frame.C.eq(C).fillna(False)
    return mask.fillna(False)


def validate_frozen_control(bundle, report, inner_scores, outer_scores):
    """Check all eighteen frozen control blocks; no metric recomputation or C selection."""
    folds = _report_folds(report)
    result = []
    blocks, rows = 0, 0
    ledger_roles = ((inner_scores, 'inner_validation'), (outer_scores, 'outer_evaluation'))
    for frame, role in ledger_roles:
        _schema(frame)
        consumed = pd.Series(False, index=frame.index)
        for fold_report in folds:
            fold = fold_report['outer_fold']
            truth = bundle.role_block(fold, role)
            prior = _prior(bundle, fold, role)
            plans = _plans(role, fold_report['selection']['selected_C'])
            for model, C in plans:
                mask = _select(frame, fold, role, model, C)
                if (consumed & mask).any():
                    raise ValueError('Control score groups overlap')
                support = validate_score_block(frame.loc[mask], truth, model, C,
                                               prior=prior if model == 'constant_reference' else None)
                consumed |= mask
                blocks += 1
            result.append({'outer_fold': fold, 'role': role, **support,
                           'score_blocks': len(plans), 'score_rows': len(truth) * len(plans),
                           'control_selected_C': float(fold_report['selection']['selected_C'])})
        if not consumed.all():
            raise ValueError('Unexpected control score row, role, model or C')
        rows += len(frame)
    expected = report['results']['execution']['score_rows_across_blocks']
    if (isinstance(expected, bool) or not isinstance(expected, int) or blocks != 18 or rows != expected):
        raise ValueError('Control block or total score coverage differs from frozen report')
    return {'status': 'verified_complete_frozen_control_without_metrics',
            'folds': result, 'score_blocks': blocks, 'score_rows': rows,
            'inner_score_rows': len(inner_scores), 'outer_score_rows': len(outer_scores),
            'metadata_columns_compared': len(dataset.MEMBERSHIP_COLUMNS),
            'unknown_query_scores_retained': True, 'metrics_computed': 0, 'candidate_selections': 0}


def validate_paired_block(treatment, control, truth, *, model, treatment_C, control_C, prior=None):
    """Gate exact row-for-row identity; selected outer C may differ between arms."""
    first = validate_score_block(treatment, truth, model, treatment_C, prior=prior)
    second = validate_score_block(control, truth, model, control_C, prior=prior)
    if model == 'logistic_candidate' and treatment_C != control_C:
        raise ValueError('Inner candidate comparisons require the same C')
    if first != second:
        raise ValueError('Paired role coverage differs')
    return {'status': 'passed_same_ID_role_truth_pairing', **first,
            'metadata_columns_compared': len(dataset.MEMBERSHIP_COLUMNS),
            'treatment_C': None if treatment_C is None else float(treatment_C),
            'control_C': None if control_C is None else float(control_C), 'metrics_computed': 0}


def validate_treatment_pairing(bundle, control_report, control_inner, control_outer,
                               treatment_inner, treatment_outer, selected_C):
    """Future full-ledger gate; caller provides the independently selected treatment Cs."""
    control_summary = validate_frozen_control(bundle, control_report, control_inner, control_outer)
    if not isinstance(selected_C, dict) or set(selected_C) != set(FOLDS):
        raise ValueError('Treatment selections must name every frozen fold exactly once')
    for C in selected_C.values():
        _candidate(C)
    paired = []
    for treatment, control, role in ((treatment_inner, control_inner, 'inner_validation'),
                                     (treatment_outer, control_outer, 'outer_evaluation')):
        _schema(treatment)
        consumed = pd.Series(False, index=treatment.index)
        for fold_report in _report_folds(control_report):
            fold = fold_report['outer_fold']
            truth = bundle.role_block(fold, role)
            prior = _prior(bundle, fold, role)
            for model, C in _plans(role, selected_C[fold]):
                control_C = fold_report['selection']['selected_C'] if model == 'logistic_selected' else C
                mask = _select(treatment, fold, role, model, C)
                if (consumed & mask).any():
                    raise ValueError('Treatment score groups overlap')
                control_mask = _select(control, fold, role, model, control_C)
                result = validate_paired_block(treatment.loc[mask], control.loc[control_mask], truth,
                                               model=model, treatment_C=C, control_C=control_C,
                                               prior=prior if model == 'constant_reference' else None)
                paired.append({'outer_fold': fold, 'role': role, 'model': model, **result})
                consumed |= mask
        if not consumed.all():
            raise ValueError('Unexpected treatment score row, role, model or C')
    if len(paired) != 18 or len(treatment_inner) + len(treatment_outer) != control_summary['score_rows']:
        raise ValueError('All eighteen full-roster paired blocks are required')
    return {'status': 'passed_complete_same_ID_treatment_control_pairing', 'paired_blocks': paired,
            'score_blocks': len(paired), 'score_rows_per_arm': control_summary['score_rows'],
            'metrics_computed': 0, 'candidate_selections': 0,
            'treatment_selection_recomputed': False}
