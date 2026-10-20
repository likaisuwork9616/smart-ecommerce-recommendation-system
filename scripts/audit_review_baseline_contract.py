"""Freeze future baseline rules and audit metadata only; never build X or fit."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
from pathlib import Path
import platform

import pandas as pd

try:
    from scripts import freeze_review_dataset as dataset
except ModuleNotFoundError:
    import freeze_review_dataset as dataset

ROOT = Path(__file__).resolve().parents[1]
CODE = 'scripts/audit_review_baseline_contract.py'
SPEC = 'reports/stage5/review_baseline_specification.json'
REPORT = 'reports/stage5/review_baseline_contract_audit.json'
GUARD = '.runtime/stage5_review_baseline_v1/input_guard.json'
RECEIPT = '.runtime/stage5_dataset_formal_execution_proof.json'
LOCK = 'requirements-lock.txt'
OLD_SPEC_SHA = '09d57ce3e30f1b6c9b7ff2ac657a7f6d2ea46c2e70b533548cb973557fa3e1f5'
OLD_REPORT_SHA = '4542b66e96e24540ec07f0c9ad679fd39e8f0dcbfcc62caa1ab62d0b2b202d56'
PRIMARY = ['purchase_month', 'purchase_dayofweek', 'purchase_hour', 'approval_wait_hours']
VERSIONS = {'python': '3.12.10', 'numpy': '2.5.4', 'pandas': '3.0.6', 'scikit-learn': '1.9.1'}
PRIVATE_INPUTS = [dataset.PRIVATE + '/' + name for name in
                  ['order_labels.csv', 'split_membership.csv', 'manifest.json']] + [RECEIPT]


def protocol():
    return {
        'role': 'future_baseline_contract_metadata_audit_no_training',
        'dataset_protocol_unchanged': True,
        'features': {'primary_order': PRIMARY,
                     'primary_dtype': 'float64',
                     'categorical': {'purchase_month': list(range(1, 13)),
                                     'purchase_dayofweek': list(range(7)),
                                     'purchase_hour': list(range(24))},
                     'one_hot': {'drop': None, 'handle_unknown': 'error',
                                 'sparse_output': False, 'dtype': 'float64', 'columns': 43},
                     'numeric': {'approval_wait_hours': '(approval-purchase).total_seconds()/3600',
                                 'log_clip_winsor': False},
                     'output_columns': 44,
                     'output_order': ['month_1_through_12', 'dayofweek_0_through_6',
                                      'hour_0_through_23', 'scaled_approval_wait_hours'],
                     'intercept_separate': True,
                     'availability': 'each_order_own_approval_t_event_proxy_only',
                     'query_clocks_before_model_fit_required': False,
                     'other_prior_17_features': 'deferred_excluded',
                     'ids_and_all_label_metadata_status_logistics_reviews': 'banned_from_X'},
        'preprocessing': {'eligible_fit_rows': 'role_label_usable_train_only',
                          'unknown_in_fit': False, 'imputer': None,
                          'numeric_scaler': {'with_mean': True, 'with_std': True,
                                             'variance_ddof': 0, 'zero_std_scale': 1},
                          'categorical_categories_fit_from_data': False,
                          'missing_nonfinite_or_invalid_X': 'stop_fold_keep_full_query_no_drop_no_zero_inference',
                          'refit_per_C_and_outer_fit': True},
        'reference': {'type': 'unsmoothed_eligible_train_low_count_divided_by_train_count',
                      'selection_candidate': False, 'compute_this_run': False},
        'main_model': {'type': 'LogisticRegression', 'package': 'scikit-learn',
                       'version': '1.9.1', 'l1_ratio': 0.0, 'penalty_argument': 'omitted_deprecated',
                       'n_jobs_argument': 'omitted', 'solver': 'lbfgs', 'dual': False,
                       'tol': 1e-8, 'max_iter': 1000, 'fit_intercept': True,
                       'class_weight': None, 'random_state': 42, 'warm_start': False, 'verbose': 0},
        'selection': {'C_candidates': [0.1, 1.0, 10.0], 'inner_train_cutoff': 'I',
                      'inner_validation_label_cutoff': 'F',
                      'objective': 'finite_average_precision_score_noninterpolated',
                      'tie_absolute_tolerance': 1e-12, 'tie_break': 'smallest_C_within_tolerance_of_max',
                      'constant_reference_competes': False, 'outer_evaluation_used': False,
                      'after_selection': 'refit_preprocessing_and_estimator_from_scratch_on_F_eligible_history',
                      'actual_selected_C': None},
        'disabled_future_changes': ['weights', 'resampling', 'early_stopping', 'calibration',
                                    'threshold_tuning', 'budget_tuning', 'automatic_retry'],
        'future_evaluation': {
            'probability_target': 'P(y=1)',
            'probability_column': 'column_matching_label_1_in_estimator.classes_',
            'score_queries': 'all_orders_including_unknown', 'metric_rows': 'role_label_usable_only',
            'required_coverage': 'full_N_known_unknown_exclusive_reasons_known_low_other',
            'primary': 'average_precision_score_noninterpolated_not_trapezoid',
            'primary_AP_undefined': 'null_if_either_class_absent',
            'secondary_roc_auc': 'null_if_either_class_absent',
            'brier': 'mean((probability-y)**2)',
            'brier_and_log_loss_support': 'defined_with_at_least_one_known_label_including_one_class',
            'binary_log_loss': 'mean(-y*log(p)-(1-y)*log(1-p));clip_only_for_log',
            'log_loss_labels': [0, 1],
            'log_probability_clip': [1e-15, 1 - 1e-15],
            'no_known_rows': 'all_metrics_null',
            'confusion': 'TP_FP_TN_FN_at_probability_greater_than_or_equal_0.5',
            'precision_recall': 'null_if_respective_denominator_is_zero',
            'macro_primary': 'equal_weight_mean_AP_only_if_all_three_months_valid_else_null_and_valid_fold_count',
            'pooled_AP': False, 'independent_fold_confidence_interval': False,
            'data_role': 'already_inspected_development_not_fresh_holdout'},
        'stop_rules': {'both_classes_required': ['inner_train_pool', 'inner_validation', 'outer_train_pool'],
                       'any_candidate_failure_or_nonfinite_AP': 'stop_fold_no_candidate_removal',
                       'insufficient_support': 'stop_fold_no_fallback_or_automatic_C',
                       'convergence_warning': 'stop_fold',
                       'nonfinite_coefficient_or_probability': 'stop_fold',
                       'probability_outside_0_1': 'stop_fold'},
        'seed_42': 'reproducibility_only_not_five_seed_experiment',
        'protected_stage4': {'status': 'pending_data', 'daily_budget': 0.1,
                             'seeds': [11, 29, 42, 73, 101], 'modified': False},
        'this_run': {'feature_build': 0, 'transform': 0, 'model_import': 0,
                     'model_instantiation': 0, 'fit': 0, 'predictions': 0,
                     'metrics': 0, 'selection': 0, 'dashboard': 0}}


def software_versions():
    actual = {'python': platform.python_version()}
    actual.update({key: importlib.metadata.version(key) for key in VERSIONS if key != 'python'})
    if actual != VERSIONS:
        raise ValueError('Software version differs from frozen baseline protocol')
    return actual


def constructor_signature(source, class_name):
    """Read accepted names/default expressions as AST; do not import the package."""
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(classes) != 1:
        raise ValueError('Installed constructor class missing or ambiguous')
    constructors = [node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == '__init__']
    if len(constructors) != 1:
        raise ValueError('Installed constructor missing or ambiguous')
    arguments = constructors[0].args
    positional = arguments.posonlyargs + arguments.args
    names = [argument.arg for argument in positional + arguments.kwonlyargs if argument.arg != 'self']
    defaults = dict(zip([argument.arg for argument in positional[-len(arguments.defaults):]],
                        [ast.unparse(value) for value in arguments.defaults])) if arguments.defaults else {}
    defaults.update({argument.arg: ast.unparse(value) for argument, value in
                     zip(arguments.kwonlyargs, arguments.kw_defaults) if value is not None})
    return {'accepted_parameters': names, 'default_expressions': defaults}


def validate_api_signatures(signatures):
    required = {'LogisticRegression': ['C', 'l1_ratio', 'solver', 'dual', 'tol', 'max_iter',
                                      'fit_intercept', 'class_weight', 'random_state', 'warm_start', 'verbose'],
                'OneHotEncoder': ['categories', 'drop', 'sparse_output', 'dtype', 'handle_unknown'],
                'StandardScaler': ['with_mean', 'with_std']}
    for name, parameters in required.items():
        if name not in signatures or not set(parameters).issubset(signatures[name]['accepted_parameters']):
            raise ValueError('Pinned local API does not support frozen baseline arguments')
    defaults = signatures['LogisticRegression']['default_expressions']
    if defaults.get('l1_ratio') != '0.0' or defaults.get('penalty') != "'deprecated'":
        raise ValueError('Pinned logistic regularization defaults differ from frozen API')
    return {'classes_checked': 3, 'frozen_argument_support': True,
            'logistic_penalty_deprecated': True, 'logistic_l1_ratio_default_zero': True,
            'objects_instantiated': 0, 'package_imports': 0}


def local_api_contract():
    distribution = importlib.metadata.distribution('scikit-learn')
    paths = {'LogisticRegression': 'sklearn/linear_model/_logistic.py',
             'OneHotEncoder': 'sklearn/preprocessing/_encoders.py',
             'StandardScaler': 'sklearn/preprocessing/_data.py'}
    signatures = {name: constructor_signature(distribution.locate_file(path).read_text(encoding='utf-8'), name)
                  for name, path in paths.items()}
    checks = validate_api_signatures(signatures)
    return {'package': 'scikit-learn', 'version': distribution.version,
            'method': 'AST_only_distribution_locate_file_no_package_import',
            'classes': {name: {'package_relative_path': paths[name], **signature}
                        for name, signature in signatures.items()}, 'verification': checks}


def ast_clock_contract(root=ROOT):
    tree = ast.parse((Path(root) / 'scripts/delay_features.py').read_text(encoding='utf-8'))
    constants = {}
    expressions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ('NUMERIC_FEATURES', 'CATEGORICAL_FEATURES'):
                constants[target.id] = ast.literal_eval(node.value)
            if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                    and target.value.id == 'result' and isinstance(target.slice, ast.Constant)
                    and target.slice.value in PRIMARY):
                expressions[target.slice.value] = ast.unparse(node.value)
    expected = {
        'purchase_month': "result['order_purchase_timestamp'].dt.month",
        'purchase_dayofweek': "result['order_purchase_timestamp'].dt.dayofweek",
        'purchase_hour': "result['order_purchase_timestamp'].dt.hour",
        'approval_wait_hours': "(result['prediction_time'] - result['order_purchase_timestamp']).dt.total_seconds() / 3600"}
    if expressions != expected:
        raise ValueError('Prior clock definitions changed')
    all_features = constants['NUMERIC_FEATURES'] + constants['CATEGORICAL_FEATURES']
    if len(all_features) != 21 or not set(PRIMARY).issubset(all_features):
        raise ValueError('Prior candidate feature contract changed')
    return {'prior_feature_count': 21, 'primary_feature_count': 4,
            'deferred_features': [name for name in all_features if name not in PRIMARY],
            'primary_expressions_AST_only': expressions,
            'source_function_executed': False, 'feature_values_computed': 0}


def old_provenance(root=ROOT):
    root = Path(root)
    spec_source = dataset.descriptor(root / dataset.SPEC, root)
    audit_source = dataset.descriptor(root / dataset.REPORT, root)
    if spec_source['sha256'] != OLD_SPEC_SHA or audit_source['sha256'] != OLD_REPORT_SHA:
        raise ValueError('Frozen dataset spec or audit changed')
    oldspec, audit = dataset.read_json(root / dataset.SPEC), dataset.read_json(root / dataset.REPORT)
    dataset.verify_sources(oldspec['sources'], root)
    if oldspec['protocol'] != dataset.protocol() or audit['protocol'] != oldspec['protocol']:
        raise ValueError('Dataset protocol changed')
    receipt = dataset.read_json(root / RECEIPT)
    if not receipt['artifacts_byte_identical'] or receipt['artifact_count'] != 5:
        raise ValueError('Original formal execution receipt did not pass')
    original_files = [dataset.SPEC, dataset.REPORT] + PRIVATE_INPUTS[:3]
    for path in original_files:
        actual = dataset.descriptor(root / path, root)
        expected = receipt['private_after_hashes'][path]
        if actual['bytes'] != expected['bytes'] or actual['sha256'] != expected['sha256']:
            raise ValueError('Original frozen artifact differs from private execution receipt')
    manifest = dataset.read_json(root / (dataset.PRIVATE + '/manifest.json'))
    if manifest['specification_sha256'] != spec_source['sha256'] or manifest['protocol'] != oldspec['protocol']:
        raise ValueError('Original manifest does not bind the actual dataset specification')
    for name in ('order_labels.csv', 'split_membership.csv'):
        actual = dataset.descriptor(root / dataset.PRIVATE / name, root)
        if any(actual[key] != manifest['files'][name][key] for key in ('bytes', 'sha256')):
            raise ValueError('Original CSV differs from its frozen private manifest')
    private = [dataset.descriptor(root / path, root) for path in PRIVATE_INPUTS]
    return oldspec, audit, oldspec['sources'] + [spec_source, audit_source], private


def make_specification(root=ROOT):
    root = Path(root)
    oldspec, _, sources, _ = old_provenance(root)
    sources += [dataset.descriptor(root / LOCK, root), dataset.descriptor(root / CODE, root)]
    if len(sources) != 18:
        raise ValueError('Expected exactly 18 source bindings')
    versions = software_versions()
    locked = dict(line.split('==', 1) for line in (root / LOCK).read_text(encoding='utf-8').splitlines() if '==' in line)
    if any(locked.get(name) != version for name, version in versions.items() if name != 'python'):
        raise ValueError('Runtime versions differ from pinned requirements')
    dataset.verify_sources(sources, root)
    return {'format_version': 1, 'role': 'future_baseline_contract_not_training_execution',
            'protocol': protocol(), 'sources': sources, 'software_versions': versions,
            'local_API_contract': local_api_contract(),
            'clock_definition_contract': ast_clock_contract(root),
            'dataset_calendar_unchanged': oldspec['calendar_split_plan'],
            'private_inputs': {'paths': PRIVATE_INPUTS, 'default_guard_path': GUARD,
                               'digests_published': False, 'historical_ingestion_verified': False},
            'public_output': REPORT, 'selected_C': None}


def freeze_specification(spec_path, guard_path, root=ROOT):
    root = Path(root)
    spec_path = dataset.safe_output(spec_path, SPEC, root)
    guard_path = dataset.safe_output(guard_path, '', root, private=True)
    spec = make_specification(root)
    _, _, _, private = old_provenance(root)
    spec_bytes = dataset.json_bytes(spec)
    spec_source = {'path': spec_path.relative_to(root.resolve()).as_posix(),
                   'bytes': len(spec_bytes), 'sha256': hashlib.sha256(spec_bytes).hexdigest()}
    guard = {'format_version': 1, 'specification': spec_source, 'private_inputs': private,
             'provenance_scope': 'local_frozen_receipt_and_manifest_not_original_ingestion_proof'}
    all_sources = spec['sources'] + private
    if spec_path == guard_path or any(path in {(root / item['path']).resolve() for item in all_sources}
                                            for path in (spec_path, guard_path)):
        raise ValueError('New output collides with an existing source')
    dataset.immutable_preflight(spec_path, spec_bytes)
    dataset.immutable_preflight(guard_path, dataset.json_bytes(guard))
    dataset.verify_sources(all_sources, root)
    dataset.immutable_write(spec_path, spec_bytes)
    dataset.immutable_write(guard_path, dataset.json_bytes(guard))
    dataset.verify_sources(all_sources + [spec_source], root)
    return spec


def verify_contract(spec, spec_path, guard_path, root=ROOT):
    root = Path(root)
    if spec != make_specification(root):
        raise ValueError('Frozen baseline protocol or source version changed')
    source = dataset.descriptor(spec_path, root)
    guard = dataset.read_json(guard_path)
    if guard['specification'] != source:
        raise ValueError('Private guard does not bind actual baseline specification bytes')
    if [item['path'] for item in guard['private_inputs']] != PRIVATE_INPUTS:
        raise ValueError('Unexpected guarded private input paths')
    dataset.verify_sources(guard['private_inputs'] + [source], root)
    return source, guard


def raw_clock_roster(orders):
    if list(orders.columns) != ['order_id', 'order_purchase_timestamp', 'order_approved_at']:
        raise ValueError('Only order IDs and two event clocks may be loaded')
    if orders.order_id.isna().any() or orders.order_id.eq('').any() or orders.order_id.duplicated().any():
        raise ValueError('Raw order IDs must be present and unique')
    purchase = dataset.parse_clock(orders.order_purchase_timestamp)
    approval = dataset.parse_clock(orders.order_approved_at)
    mask = purchase.notna() & approval.notna() & approval.ge(purchase) & approval.lt(dataset.COHORT_CUTOFF)
    roster = pd.DataFrame({'order_id': orders.loc[mask, 'order_id'],
                           'purchase_time': purchase.loc[mask], 'prediction_time': approval.loc[mask]})
    roster = roster.sort_values(['prediction_time', 'order_id']).reset_index(drop=True)
    return roster


def block_metadata(frame, expected_roster, cutoff, expected_summary):
    if list(frame.order_id) != list(expected_roster.order_id):
        raise ValueError('Role IDs, full query denominator or canonical order changed')
    if not frame.prediction_time.reset_index(drop=True).equals(expected_roster.prediction_time.reset_index(drop=True)):
        raise ValueError('Role own approval clock differs from raw source')
    if not frame.window_deadline.eq(frame.prediction_time + pd.Timedelta(days=60)).all():
        raise ValueError('H60 deadline changed')
    if not frame.observation_cutoff.eq(cutoff).all():
        raise ValueError('Role label cutoff changed')
    maturity = frame.window_deadline.lt(cutoff)
    if not frame.horizon_complete.eq(maturity).all():
        raise ValueError('Maturity flags changed')
    usable = frame.role_label_usable
    if (frame.loc[~usable, 'y'].notna().any() or frame.loc[usable, 'y'].isna().any()
            or not frame.loc[usable, 'y'].isin([0, 1]).all()):
        raise ValueError('Unknown target imputed or usable target missing')
    if not usable.eq(frame.label_state.isin(['known_low_1_2', 'known_other_3_5'])).all():
        raise ValueError('Label state disagrees with eligible fitting rows')
    if not frame.loc[frame.y.eq(1).fillna(False), 'label_state'].eq('known_low_1_2').all():
        raise ValueError('Positive target and state disagree')
    if not frame.loc[frame.y.eq(0).fillna(False), 'label_state'].eq('known_other_3_5').all():
        raise ValueError('Other-score target and state disagree')
    answered = frame.first_visible_answer_at.notna()
    if frame.loc[answered, 'first_visible_answer_at'].ge(cutoff).any():
        raise ValueError('Future answer metadata leaked into role')
    good_clock = (maturity & frame.first_visible_answer_at.gt(frame.prediction_time)
                  & frame.first_visible_answer_at.le(frame.window_deadline))
    if (usable & ~good_clock).any():
        raise ValueError('Eligible label violates answer/maturity boundary')
    states = {state: int(frame.label_state.eq(state).sum()) for state in dataset.STATES}
    summary = {'orders': len(frame), 'mature_windows': int(maturity.sum()),
               'immature_windows': int((~maturity).sum()), 'usable_labels': int(usable.sum()),
               'unknown_or_ineligible_labels': int((~usable).sum()),
               'low_1_2': int(frame.y.eq(1).sum()), 'other_3_5': int(frame.y.eq(0).sum()),
               'exclusive_label_states': states}
    if sum(states.values()) != len(frame) or any(summary[key] != expected_summary[key] for key in summary):
        raise ValueError('Frozen role aggregate changed')
    summary.update({'unknown_preprocessing_fit_rows': 0,
                    'feature_values_built': 0, 'source_clock_support_orders': len(expected_roster),
                    'both_classes_supported': summary['low_1_2'] > 0 and summary['other_3_5'] > 0,
                    'historical_ingestion_verified': False, 'violations': 0})
    return summary


def support_decision(blocks):
    required = ('inner_train_pool', 'inner_validation', 'outer_train_pool')
    return 'supported_for_future_offline_baseline_only' if all(blocks[name]['both_classes_supported'] for name in required) else 'insufficient_support_stop_fold'


def metadata_audit(roster, labels, membership, old_audit):
    global_summary = block_metadata(labels, roster, dataset.OBSERVATION_CUTOFF,
                                    old_audit['final_observation_labels'])
    plans = old_audit['nested_calendar_development_support']
    expected_blocks = {(fold['calendar']['outer_fold'], role) for fold in plans for role in fold['roles']}
    if set(zip(membership.outer_fold, membership.role)) != expected_blocks:
        raise ValueError('Missing or unexpected calendar/role blocks')
    if membership.duplicated(['outer_fold', 'role', 'order_id']).any():
        raise ValueError('Duplicate order in role')
    folds = []
    for fold in plans:
        plan = fold['calendar']
        outer, inner = pd.Timestamp(plan['outer_fit_at']), pd.Timestamp(plan['inner_fit_at'])
        end_outer = pd.Timestamp(plan['outer_query_end_exclusive'])
        end_inner = pd.Timestamp(plan['inner_query_end_exclusive'])
        roles = [('inner_train_pool', roster.prediction_time.lt(inner), inner, inner),
                 ('inner_validation', roster.prediction_time.ge(inner) & roster.prediction_time.lt(end_inner), outer, inner),
                 ('outer_train_pool', roster.prediction_time.lt(outer), outer, outer),
                 ('outer_evaluation', roster.prediction_time.ge(outer) & roster.prediction_time.lt(end_outer), dataset.OBSERVATION_CUTOFF, outer)]
        summaries, frames = {}, {}
        for role, mask, cutoff, fit_at in roles:
            frame = membership.loc[(membership.outer_fold == plan['outer_fold']) & (membership.role == role)]
            if not frame.fit_at.eq(fit_at).all():
                raise ValueError('Role fit clock changed')
            summary = block_metadata(frame, roster.loc[mask], cutoff, fold['roles'][role])
            summary.update({'fit_at': str(fit_at), 'label_cutoff_exclusive': str(cutoff),
                            'own_t_event_proxy_only': True,
                            'fit_feature_rows_if_future_training': summary['usable_labels'] if role.endswith('train_pool') else 0,
                            'query_denominator_if_future_scoring': len(frame) if not role.endswith('train_pool') else 0})
            summaries[role], frames[role] = summary, frame
        overlaps = {}
        for a, b in [('inner_train_pool', 'inner_validation'), ('outer_train_pool', 'outer_evaluation'),
                     ('inner_train_pool', 'outer_evaluation'), ('inner_validation', 'outer_evaluation')]:
            overlaps[a + '_vs_' + b] = len(set(frames[a].order_id) & set(frames[b].order_id))
        if any(overlaps.values()):
            raise ValueError('Train-query role order overlap')
        folds.append({'outer_fold': plan['outer_fold'], 'calendar': plan, 'roles': summaries,
                      'train_query_order_overlap': overlaps, 'support': support_decision(summaries),
                      'selected_C': None, 'metrics_computed': False})
    return global_summary, folds


def run_audit(spec, spec_path, guard_path, output_path, root=ROOT):
    root = Path(root)
    spec_path = dataset.safe_output(spec_path, SPEC, root)
    guard_path = dataset.safe_output(guard_path, '', root, private=True)
    output_path = dataset.safe_output(output_path, REPORT, root)
    if len({spec_path, guard_path, output_path}) != 3:
        raise ValueError('Specification, guard and audit paths collide')
    spec_source, guard = verify_contract(spec, spec_path, guard_path, root)
    oldspec, old_audit, _, _ = old_provenance(root)
    all_bound = spec['sources'] + guard['private_inputs'] + [spec_source, dataset.descriptor(guard_path, root)]
    if output_path in {(root / item['path']).resolve() for item in all_bound}:
        raise ValueError('Audit output collides with bound source')
    orders = pd.read_csv(root / dataset.ORDERS,
                         usecols=['order_id', 'order_purchase_timestamp', 'order_approved_at'], dtype='string')
    # Explicit order: no status, promise, customer, item, payment or review values loaded.
    orders = orders[['order_id', 'order_purchase_timestamp', 'order_approved_at']]
    roster = raw_clock_roster(orders)
    labels = dataset.read_private_csv((root / dataset.PRIVATE / 'order_labels.csv').read_bytes(), dataset.LABEL_COLUMNS)
    membership = dataset.read_private_csv((root / dataset.PRIVATE / 'split_membership.csv').read_bytes(), dataset.MEMBERSHIP_COLUMNS)
    global_summary, folds = metadata_audit(roster, labels, membership, old_audit)
    if len(roster) != oldspec['expected_existing_cohort_orders']:
        raise ValueError('Primary cohort changed')
    dataset.verify_sources(all_bound, root)
    result = {'format_version': 1, 'status': 'passed_baseline_contract_metadata_only',
              'decision': 'rules_frozen_no_training_real_ingestion_pending',
              'specification': spec_source, 'sources': spec['sources'],
              'protocol': protocol(), 'software_versions': software_versions(),
              'local_API_contract': spec['local_API_contract'],
              'clock_definition_contract': spec['clock_definition_contract'],
              'global_order_metadata': global_summary, 'nested_calendar_support': folds,
              'private_provenance': {'guard_path': guard_path.relative_to(root.resolve()).as_posix(),
                                     'original_manifest_and_receipt_verified': True,
                                     'private_bound_files': len(guard['private_inputs']),
                                     'private_digest_public': False},
              'verification': {'public_source_bindings_before_after': len(spec['sources']),
                               'private_source_bindings_before_after': len(guard['private_inputs']),
                               'order_metadata_rows': len(labels), 'membership_rows': len(membership),
                               'role_blocks': 12, 'required_class_support_contexts': 9,
                               'unknown_nonnull_y': 0, 'availability_violations': 0,
                               'raw_data_columns_parsed': ['order_id', 'order_purchase_timestamp', 'order_approved_at'],
                               'all_model_and_feature_execution': protocol()['this_run']},
              'limitations': ['Event clocks do not prove ingestion, source revisions or original availability at own t.',
                              'Unknown/nonresponse coverage can be selective; no all-population performance claim.',
                              'No baseline reference probability, C selection, metric, X value or fitted object was produced.',
                              'Already inspected rolling development folds are not independent or new held-out tests.',
                              'Stage 4 remains pending data with unchanged daily 10% and five seeds.']}
    dataset.immutable_preflight(output_path, dataset.json_bytes(result))
    dataset.verify_sources(all_bound, root)
    dataset.immutable_write(output_path, dataset.json_bytes(result))
    if dataset.read_json(output_path) != result:
        raise ValueError('Audit report exact JSON readback mismatch')
    dataset.verify_sources(all_bound, root)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--specification', default=SPEC)
    parser.add_argument('--output', default=REPORT)
    parser.add_argument('--guard', default=GUARD)
    args = parser.parse_args(argv)
    spec_path = dataset.safe_output(ROOT / args.specification, SPEC)
    report_path = dataset.safe_output(ROOT / args.output, REPORT)
    guard_path = dataset.safe_output(ROOT / args.guard, '', private=True)
    if len({spec_path, report_path, guard_path}) != 3:
        raise ValueError('Output paths collide')
    if args.specification_only:
        spec = freeze_specification(spec_path, guard_path)
        print(__import__('json').dumps({'status': 'baseline_specification_frozen', 'source_bindings': len(spec['sources']), 'fits': 0}))
        return
    result = run_audit(dataset.read_json(spec_path), spec_path, guard_path, report_path)
    print(__import__('json').dumps({'status': result['status'], 'orders': result['verification']['order_metadata_rows'],
                                   'role_blocks': 12, 'fits': 0, 'selected_C': None}))


if __name__ == '__main__':
    main()
