"""Execute the separately bound, frozen three-feature ablation; never refit control.

This module performs no I/O. The formal entry point must verify its dispatcher
binding and reserve an empty output namespace before calling execute_training.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import time

import numpy as np
import pandas as pd

from scripts import prepare_review_month_ablation as policy
from scripts import freeze_review_dataset as files
from scripts import review_baseline_evaluation as evaluation
from scripts import review_baseline_pipeline as common
from scripts import review_baseline_sources as sources
from scripts import review_month_ablation_pairing as pairing
from scripts import review_month_ablation_pipeline as pipeline
from scripts.run_review_baseline import FOLDS, SCORE_COLUMNS, _csv_bytes

GuardedReviewMonthAblation = pipeline.GuardedReviewMonthAblation
FIT_AUDIT_KEYS = ('format_version', 'fit_records', 'completed_estimator_fits',
                  'inner_fits_completed', 'outer_fits_completed', 'model_objects_persisted')
FIT_RECORD_KEYS = ('fit_sequence', 'outer_fold', 'role', 'C', 'fit_at', 'context_version',
                   'eligible_order_ids', 'train_pool_order_ids', 'train_pool_orders',
                   'unknown_excluded_from_fit', 'eligible_orders', 'eligible_low_1_2',
                   'eligible_other_3_5', 'output_columns', 'scaler_mean', 'scaler_variance',
                   'scaler_scale', 'scaler_samples', 'coefficient_values', 'intercept_values',
                   'classes', 'seconds')
PUBLIC_RESULT_KEYS = ('outer_folds', 'fit_context_audits', 'aggregate_selected',
                      'aggregate_reference', 'paired_comparison', 'execution')
METRIC_NAMES = ('average_precision', 'roc_auc', 'brier', 'binary_log_loss',
                'TP', 'FP', 'TN', 'FN', 'precision', 'recall')


class TrainingStopped(RuntimeError):
    def __init__(self, context, cause):
        self.context = deepcopy(context)
        self.cause_type = type(cause).__name__
        super().__init__('Ablation stopped without fallback: ' + self.cause_type)


def audit_contract():
    return {'top_level_keys': list(FIT_AUDIT_KEYS), 'record_keys': list(FIT_RECORD_KEYS),
            'record_count': 12, 'fit_sequence': 'one_based_execution_order',
            'inner_fit_count': 9, 'outer_fit_count': 3,
            'output_columns': list(pipeline.OUTPUT_COLUMNS), 'coefficient_shape': [1, 32],
            'intercept_shape': [1], 'scaler_shape': [1], 'classes': [0, 1],
            'unknown_rows_excluded_before_preprocessing': True,
            'model_objects_persisted': False}


def dispatcher_contract():
    return {'version': 'stage5_review_month_ablation_dispatcher_v1',
            'result_keys': list(PUBLIC_RESULT_KEYS), 'fit_audit': audit_contract(),
            'preflight': 'all_12_full_roles_all_9_required_two_class_contexts_control_18_blocks',
            'fits': 'fresh_3_inner_candidates_and_1_outer_refit_per_fold_total_12',
            'selection': 'three_calls_own_inner_AP_only_original_tolerance_and_tie_break',
            'query_truth_fields_cleared': list(sources.FUTURE_QUERY_COLUMNS),
            'source_checks': 'before_preflight_before_each_fit_after_each_prediction_after_pairing',
            'control': 'read_frozen_scores_and_report_only_zero_fits_zero_reselection_zero_metric_recomputation',
            'accepted_treatment_file_digests': {
                'inner_scores.csv': ['bytes', 'sha256'], 'outer_scores.csv': ['bytes', 'sha256'],
                'fit_audit.json': ['bytes', 'sha256']},
            'accepted_public_results_digest': ['bytes', 'sha256'],
            'comparison': 'treatment_minus_frozen_control_null_if_either_null_macro_requires_both_all3',
            'failure': 'stop_with_exact_completed_fit_count_no_retry_no_candidate_removal',
            'publication': 'delegated_to_bound_private_writer_after_all_18_pairings_pass'}


def _preflight(bundle, tracker):
    """Validate all fit clocks and complete query rosters before creating a model."""
    raw, context, blocks, safe = bundle.raw_orders, bundle.context, {}, {}
    for fold in FOLDS:
        for role in ('inner_train_pool', 'inner_validation', 'outer_train_pool', 'outer_evaluation'):
            tracker.update(phase='all_roles_preflight', outer_fold=fold, role=role, C=None)
            truth = bundle.role_block(fold, role)
            _, canonical, fit_at = common._role_block(raw, truth, fold, role, context)
            # _role_block filters a requested role; reject a caller supplying extra rows.
            pd.testing.assert_frame_equal(truth.reset_index(drop=True), canonical,
                                          check_dtype=False, check_exact=True)
            evaluation.label_support(truth)
            if role.endswith('train_pool'):
                common._training_eligibility(truth, fit_at)
                evaluation.require_both_classes(truth)
            else:
                if role == 'inner_validation':
                    evaluation.require_both_classes(truth)
                query = bundle.prediction_block(fold, role)
                expected = truth.copy(deep=True)
                for name in sources.FUTURE_QUERY_COLUMNS:
                    expected[name] = pd.NA
                pd.testing.assert_frame_equal(query.reset_index(drop=True), expected.reset_index(drop=True),
                                              check_dtype=False, check_exact=True)
                if not query.loc[:, list(sources.FUTURE_QUERY_COLUMNS)].isna().all().all():
                    raise ValueError('Prediction input contains future truth')
                safe[(fold, role)] = query.copy(deep=True)
            blocks[(fold, role)] = truth.copy(deep=True)
    tracker.update(phase='frozen_control_preflight', outer_fold=None, role=None, C=None)
    report, scores = bundle.control_report, bundle.control_scores
    if set(scores) != {'inner_scores.csv', 'outer_scores.csv'}:
        raise ValueError('Only the two frozen control ledgers are accepted')
    pairing.validate_frozen_control(bundle, report, scores['inner_scores.csv'], scores['outer_scores.csv'])
    # Check frozen report shape/coverage now, never choose C or calculate control metrics.
    for fold_report in report['results']['outer_folds']:
        fold = fold_report['outer_fold']
        for field, role in [('inner_reference', 'inner_validation'), ('outer_selected', 'outer_evaluation'),
                            ('outer_reference', 'outer_evaluation')]:
            _check_evaluation(fold_report[field], evaluation.label_support(blocks[(fold, role)])[0])
        for candidate in fold_report['inner_candidates']:
            _check_evaluation(candidate['evaluation'],
                              evaluation.label_support(blocks[(fold, 'inner_validation')])[0])
    _check_control_aggregate(report)
    return raw, context, blocks, safe, report, scores


def _check_evaluation(value, coverage):
    if set(value) != {'coverage', 'metrics'} or value['coverage'] != coverage:
        raise ValueError('Frozen control evaluation coverage differs from the paired truth')
    metrics = value['metrics']
    if set(metrics) != set(METRIC_NAMES):
        raise ValueError('Frozen control metric schema changed')
    for number in metrics.values():
        if number is not None and (isinstance(number, (bool, np.bool_))
                                   or not isinstance(number, (int, float)) or not np.isfinite(number)):
            raise ValueError('Frozen control metric is not nullable finite numeric')


def _check_control_aggregate(report):
    aggregate = report['results']['aggregate_selected']
    expected_keys = {'macro_average_precision', 'valid_folds', 'required_folds', 'weighting',
                     'pooled_average_precision_computed', 'independent_fold_confidence_interval'}
    valid = sum(item['outer_selected']['metrics']['average_precision'] is not None
                for item in report['results']['outer_folds'])
    value = aggregate['macro_average_precision']
    if (set(aggregate) != expected_keys or aggregate['valid_folds'] != valid
            or aggregate['required_folds'] != 3 or aggregate['weighting'] != 'equal_month_weight'
            or aggregate['pooled_average_precision_computed'] is not False
            or aggregate['independent_fold_confidence_interval'] is not False
            or (valid < 3 and value is not None) or (valid == 3 and value is None)):
        raise ValueError('Frozen control macro coverage or aggregation policy changed')
    if value is not None and (isinstance(value, (bool, np.bool_))
                              or not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= value <= 1):
        raise ValueError('Frozen control macro must be nullable finite AP')


def _diagnostics(model, raw, block, fold, role, C, seconds, sequence, context):
    support = evaluation.require_both_classes(block)
    state = model.audit_state()
    ids = tuple(block.loc[block.role_label_usable, 'order_id'])
    expected_context = (fold, role, common._plan(fold, role)[2])
    if (state['state'] != 'FITTED' or state['C'] != C or state['fit_context'] != expected_context
            or state['context_version'] != context.context_version
            or state['eligible_order_ids'] != ids or state['train_pool_order_ids'] != tuple(block.order_id)
            or state['scaler_samples'] != len(ids) or tuple(state['output_columns']) != pipeline.OUTPUT_COLUMNS):
        raise ValueError('Actual fitted state, full role, eligible roster or fixed32 output changed')
    for name, shape in [('scaler_mean', (1,)), ('scaler_variance', (1,)), ('scaler_scale', (1,)),
                        ('coefficient_values', (1, 32)), ('intercept_values', (1,))]:
        values = np.asarray(state[name])
        if values.shape != shape or not np.isfinite(values).all():
            raise ValueError('Fitted diagnostics shape or finiteness changed')
    if list(state['classes']) != [0, 1] or (state['scaler_variance'] < 0).any() or (state['scaler_scale'] <= 0).any():
        raise ValueError('Fitted classes or scaler moments changed')
    # Reconstruct raw eligible waits without building an additional feature matrix.
    clocks = raw.set_index('order_id').loc[list(ids)]
    waits = ((pd.to_datetime(clocks.order_approved_at) - pd.to_datetime(clocks.order_purchase_timestamp))
             .dt.total_seconds().to_numpy(dtype='float64') / 3600)
    if (not np.isclose(state['scaler_mean'][0], waits.mean(), rtol=1e-12, atol=1e-12)
            or not np.isclose(state['scaler_variance'][0], waits.var(ddof=0), rtol=1e-12, atol=1e-12)):
        raise ValueError('Scaler moments do not describe eligible training rows')
    private = {'fit_sequence': sequence, 'outer_fold': fold, 'role': role, 'C': float(C),
               'fit_at': str(expected_context[2]), 'context_version': state['context_version'],
               'eligible_order_ids': list(ids), 'train_pool_order_ids': list(block.order_id),
               'train_pool_orders': len(block), 'unknown_excluded_from_fit': support['unknown_or_ineligible_labels'],
               'eligible_orders': len(ids), 'eligible_low_1_2': support['known_low_1_2'],
               'eligible_other_3_5': support['known_other_3_5'], 'output_columns': list(state['output_columns']),
               'scaler_mean': state['scaler_mean'].tolist(), 'scaler_variance': state['scaler_variance'].tolist(),
               'scaler_scale': state['scaler_scale'].tolist(), 'scaler_samples': state['scaler_samples'],
               'coefficient_values': state['coefficient_values'].tolist(),
               'intercept_values': state['intercept_values'].tolist(), 'classes': state['classes'].tolist(),
               'seconds': float(seconds)}
    public = {key: private[key] for key in ('fit_sequence', 'outer_fold', 'role', 'C', 'fit_at',
              'train_pool_orders', 'unknown_excluded_from_fit', 'eligible_orders',
              'eligible_low_1_2', 'eligible_other_3_5')}
    public.update(output_columns=32, eligible_roster_and_scaler_sample_count_verified=True)
    return private, public


def _ledger(block, probabilities, model, C):
    if list(probabilities.index) != list(block.order_id):
        raise ValueError('Predictions must retain every query ID in canonical order')
    result = block.copy(deep=True)
    result.insert(2, 'model', model)
    result.insert(3, 'C', pd.Series(C, index=result.index, dtype='Float64'))
    result['probability_low_1_2'] = probabilities.to_numpy(dtype='float64')
    return result.loc[:, SCORE_COLUMNS]


def metric_difference(treatment, control):
    """Differences preserve missing values, including undefined confusion ratios."""
    if set(treatment) != set(METRIC_NAMES) or set(control) != set(METRIC_NAMES):
        raise ValueError('A paired metric group must contain the fixed metric names')
    result = {}
    for name in METRIC_NAMES:
        first, second = treatment[name], control[name]
        for value in (first, second):
            if value is not None and (isinstance(value, (bool, np.bool_))
                                      or not isinstance(value, (int, float)) or not np.isfinite(value)):
                raise ValueError('Metric differences require nullable finite numbers')
        result[name] = None if first is None or second is None else first - second
    return result


def paired_comparison(treatment_folds, control_report):
    control_folds = control_report['results']['outer_folds']
    if ([item['outer_fold'] for item in treatment_folds] != list(FOLDS)
            or [item['outer_fold'] for item in control_folds] != list(FOLDS)):
        raise ValueError('Paired comparisons require all three folds in frozen order')
    groups = []
    for first, second in zip(treatment_folds, control_folds):
        pairs = [('inner_validation', 'constant_reference', None, None, first['inner_reference'], second['inner_reference'])]
        if ([item['C'] for item in first['inner_candidates']] != list(evaluation.CANDIDATES)
                or [item['C'] for item in second['inner_candidates']] != list(evaluation.CANDIDATES)):
            raise ValueError('Paired comparisons require all three same-C candidates')
        for left, right in zip(first['inner_candidates'], second['inner_candidates']):
            pairs.append(('inner_validation', 'logistic_candidate', left['C'], right['C'], left['evaluation'], right['evaluation']))
        pairs.extend([('outer_evaluation', 'constant_reference', None, None, first['outer_reference'], second['outer_reference']),
                      ('outer_evaluation', 'logistic_selected', first['selection']['selected_C'], second['selection']['selected_C'],
                       first['outer_selected'], second['outer_selected'])])
        for role, model, first_C, second_C, left, right in pairs:
            if left['coverage'] != right['coverage']:
                raise ValueError('Paired comparison coverage differs')
            if model == 'constant_reference' and left != right:
                raise ValueError('Constant reference metrics differ despite the same eligible prior and truth')
            groups.append({'outer_fold': first['outer_fold'], 'role': role, 'model': model,
                           'treatment_C': first_C, 'control_C': second_C,
                           'coverage': deepcopy(left['coverage']),
                           'treatment_minus_control': metric_difference(left['metrics'], right['metrics'])})
    treatment = evaluation.macro_average_precision([item['outer_selected'] for item in treatment_folds])
    _check_control_aggregate(control_report)
    control = control_report['results']['aggregate_selected']
    first, second = treatment['macro_average_precision'], control['macro_average_precision']
    return {'scope': 'already_inspected_nested_rolling_development_not_unseen_holdout',
            'paired_groups': groups, 'group_count': 18,
            'macro_average_precision': {'treatment': first, 'control': second,
                'treatment_minus_control': None if first is None or second is None else first - second,
                'treatment_valid_folds': treatment['valid_folds'], 'control_valid_folds': control['valid_folds'],
                'required_valid_folds_per_arm': 3, 'weighting': 'equal_month_weight'},
            'control_metrics': 'reused_frozen_report_no_metric_recomputation_or_C_reselection',
            'undefined_difference_policy': 'null_if_either_arm_null_never_zero_imputation',
            'independent_fold_confidence_interval': False, 'new_success_threshold': None}


def _execute_training(bundle, specification, emit, verify_sources, tracker):
    if specification.get('execution_plan') != policy.execution_plan():
        raise ValueError('Training requires the exact frozen ablation execution policy')
    verify_sources()
    raw, context, blocks, safe, control_report, control_scores = _preflight(bundle, tracker)
    verify_sources()
    private_fits, public_fits, inner_ledgers, outer_ledgers, folds = [], [], [], [], []
    # Retain all instances until completion so accidental instance reuse is detectable.
    instances = []

    def fit_predict(fold, train_role, query_role, C):
        tracker.update(outer_fold=fold, role=train_role, C=float(C), phase='source_before_fit')
        verify_sources()
        tick = time.perf_counter()
        tracker['phase'] = 'model_construction'
        model = GuardedReviewMonthAblation(C, context=context)
        if any(model is previous for previous in instances):
            raise ValueError('Every candidate and outer context requires a fresh model instance')
        instances.append(model)
        tracker['phase'] = 'fit'
        model.fit_orders(raw, blocks[(fold, train_role)].copy(deep=True), outer_fold=fold, role=train_role)
        tracker['completed_estimator_fits'] += 1
        tracker['phase'] = 'prediction'
        predictions = model.predict_orders(raw, safe[(fold, query_role)].copy(deep=True), outer_fold=fold, role=query_role)
        tracker['phase'] = 'source_after_prediction'
        verify_sources()
        tracker['phase'] = 'evaluation_and_fit_audit'
        metrics = evaluation.evaluate_role(predictions, blocks[(fold, query_role)])
        private, public = _diagnostics(model, raw, blocks[(fold, train_role)], fold, train_role, C,
                                       time.perf_counter() - tick, tracker['completed_estimator_fits'], context)
        private_fits.append(private)
        public_fits.append(public)
        emit({'phase': 'fit_complete', 'outer_fold': fold, 'role': train_role, 'C': float(C),
              'completed_estimator_fits': tracker['completed_estimator_fits']})
        return predictions, metrics

    for fold in FOLDS:
        inner_train, inner_truth = blocks[(fold, 'inner_train_pool')], blocks[(fold, 'inner_validation')]
        inner_prior = evaluation.constant_reference_probability(inner_train)
        inner_reference = pd.Series(inner_prior, index=pd.Index(inner_truth.order_id, name='order_id'), dtype='float64')
        inner_reference_evaluation = evaluation.evaluate_role(inner_reference, inner_truth)
        inner_ledgers.append(_ledger(inner_truth, inner_reference, 'constant_reference', None))
        candidates, candidate_AP = [], {}
        for C in evaluation.CANDIDATES:
            probabilities, metrics = fit_predict(fold, 'inner_train_pool', 'inner_validation', C)
            AP = metrics['metrics']['average_precision']
            if AP is None or isinstance(AP, (bool, np.bool_)) or not np.isfinite(AP) or not 0 <= AP <= 1:
                raise ValueError('Every candidate must have finite inner AP; no failed candidate can be removed')
            candidates.append({'C': float(C), 'evaluation': metrics})
            candidate_AP[C] = AP
            inner_ledgers.append(_ledger(inner_truth, probabilities, 'logistic_candidate', C))
        tracker.update(phase='independent_treatment_selection', role='inner_validation', C=None)
        selection = evaluation.select_candidate(candidate_AP)
        chosen = selection['selected_C']
        outer_train, outer_truth = blocks[(fold, 'outer_train_pool')], blocks[(fold, 'outer_evaluation')]
        outer_prior = evaluation.constant_reference_probability(outer_train)
        outer_reference = pd.Series(outer_prior, index=pd.Index(outer_truth.order_id, name='order_id'), dtype='float64')
        probabilities, outer_evaluation = fit_predict(fold, 'outer_train_pool', 'outer_evaluation', chosen)
        reference_evaluation = evaluation.evaluate_role(outer_reference, outer_truth)
        outer_ledgers.extend([_ledger(outer_truth, probabilities, 'logistic_selected', chosen),
                              _ledger(outer_truth, outer_reference, 'constant_reference', None)])
        folds.append({'outer_fold': fold, 'inner_training_support': evaluation.require_both_classes(inner_train),
                      'inner_reference': inner_reference_evaluation, 'inner_candidates': candidates,
                      'selection': selection, 'outer_selected': outer_evaluation, 'outer_reference': reference_evaluation})
    tracker.update(phase='complete_fit_count', outer_fold=None, role=None, C=None)
    if (tracker['completed_estimator_fits'] != 12 or len(private_fits) != 12
            or sum(item['role'] == 'inner_train_pool' for item in private_fits) != 9
            or sum(item['role'] == 'outer_train_pool' for item in private_fits) != 3):
        raise ValueError('Exactly nine inner fits and three outer refits are required')
    inner, outer = pd.concat(inner_ledgers, ignore_index=True), pd.concat(outer_ledgers, ignore_index=True)
    tracker['phase'] = 'complete_same_id_pairing'
    selected = {item['outer_fold']: item['selection']['selected_C'] for item in folds}
    paired = pairing.validate_treatment_pairing(bundle, control_report,
        control_scores['inner_scores.csv'], control_scores['outer_scores.csv'], inner, outer, selected)
    paired['independent_treatment_selection'] = {
        'source': 'treatment_inner_validation_AP_only',
        'folds': [{'outer_fold': item['outer_fold'], **deepcopy(item['selection'])} for item in folds],
        'control_C_used': False, 'selection_calls': 3}
    paired['constant_reference_equality'] = True
    tracker['phase'] = 'paired_metric_comparison'
    comparison = paired_comparison(folds, control_report)
    tracker['phase'] = 'final_source_verification'
    verify_sources()
    public = {'outer_folds': folds, 'fit_context_audits': public_fits,
              'aggregate_selected': evaluation.macro_average_precision([item['outer_selected'] for item in folds]),
              'aggregate_reference': evaluation.macro_average_precision([item['outer_reference'] for item in folds]),
              'paired_comparison': comparison,
              'execution': {'estimator_fits_completed': 12, 'inner_candidates_evaluated': 9,
                  'outer_refits_completed': 3, 'reference_prior_computations': 6,
                  'prediction_blocks_completed': 18, 'score_rows_across_blocks': len(inner) + len(outer),
                  'all_queries_scored_including_unknown': True, 'unknown_fitted_or_used_in_metrics': False,
                  'outer_labels_used_in_selection': False, 'control_fits': 0, 'control_candidate_selections': 0,
                  'control_metrics_recomputed': 0, 'treatment_candidate_selections': 3,
                  'automatic_retries': 0, 'partial_success': False}}
    fit_audit = {'format_version': 1, 'fit_records': private_fits, 'completed_estimator_fits': 12,
                 'inner_fits_completed': 9, 'outer_fits_completed': 3, 'model_objects_persisted': False}
    # Bind the exact accepted payloads before they cross the publication boundary.
    # These digests stay private; the writer must reject later in-memory mutation.
    tracker['phase'] = 'accepted_payload_binding'
    payloads = {'inner_scores.csv': _csv_bytes(inner), 'outer_scores.csv': _csv_bytes(outer),
                'fit_audit.json': files.json_bytes(fit_audit)}
    paired['accepted_treatment_file_digests'] = {
        name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in payloads.items()}
    public_bytes = files.json_bytes(public)
    paired['accepted_public_results_digest'] = {
        'bytes': len(public_bytes), 'sha256': hashlib.sha256(public_bytes).hexdigest()}
    return public, inner, outer, fit_audit, paired


def execute_training(bundle, specification, *, emit=None, verify_sources=None):
    tracker = {'phase': 'execution_specification_validation', 'outer_fold': None,
               'role': None, 'C': None, 'completed_estimator_fits': 0}
    try:
        return _execute_training(bundle, specification, emit or (lambda _: None),
                                 verify_sources or bundle.verify_stable, tracker)
    except Exception as cause:
        raise TrainingStopped(tracker, cause) from cause
