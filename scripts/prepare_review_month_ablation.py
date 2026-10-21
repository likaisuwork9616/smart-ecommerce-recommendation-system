"""Freeze and accept ablation execution policy/source gates; never train."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import freeze_review_dataset as files
from scripts import review_baseline_sources as baseline_sources
from scripts import run_review_baseline as control
from scripts import review_month_ablation_sources as sources

SPEC = 'reports/stage5/review_month_ablation_execution_specification.json'
REPORT = 'reports/stage5/review_month_ablation_execution_preflight.json'
PRIVATE = '.runtime/stage5_review_month_ablation_execution_v1'
GUARD = PRIVATE + '/input_guard.json'
FUTURE_PRIVATE = '.runtime/stage5_review_month_ablation_training_v1'
FUTURE_REPORT = 'reports/stage5/review_month_ablation_training.json'
FUTURE_FILES = ('inner_scores.csv', 'outer_scores.csv', 'fit_audit.json',
                'paired_acceptance.json', 'manifest.json', 'failure_receipt.json')
CODE = ('scripts/prepare_review_month_ablation.py', 'scripts/review_month_ablation_sources.py',
        'scripts/review_month_ablation_pairing.py', 'tests/test_prepare_review_month_ablation.py',
        'tests/test_review_month_ablation_sources.py', 'tests/test_review_month_ablation_pairing.py')


def execution_plan():
    return {
        'version': 'stage5_review_month_ablation_execution_v1',
        'binding_scope': 'execution_policy_source_and_pairing_gates_training_dispatcher_not_implemented',
        'training_authorized_this_run': False,
        'future_training_dispatcher': 'requires_separate_code_and_test_binding_before_first_fit',
        'outer_folds': list(files.OUTER_MONTHS),
        'C_candidates': [0.1, 1.0, 10.0],
        'future_inner_fits': 9, 'future_outer_refits': 3, 'future_control_fits': 0,
        'treatment': 'drop_purchase_month_only_three_features_fixed32',
        'selection': 'own_inner_validation_AP_max_absolute_tolerance_1e-12_tie_smallest_C',
        'control_C_cannot_set_treatment_C': True,
        'preprocessing': 'fresh_instance_per_candidate_and_outer_context_eligible_training_only',
        'training_labels': 'own_fit_H60_mature_and_visible_answers_only_unknown_y_nullable',
        'prediction_input': 'full_query_roster_with_all_seven_future_truth_columns_cleared',
        'metric_input': 'separate_own_role_truth_after_full_query_prediction',
        'reference': 'same_eligible_training_unsmoothed_class_prior_not_a_candidate',
        'threshold': 0.5, 'outer_outcomes_in_selection': False,
        'control': 'existing_frozen_four_feature_inner_and_outer_scores_no_refit_or_reselection',
        'failure_policy': 'stop_complete_run_no_candidate_removal_fallback_retry_or_partial_success',
        'pre_fit_gate': 'verify_all_sources_full_roles_control_pairing_and_empty_output_namespace',
        'source_checks': 'before_after_load_before_each_fit_after_prediction_before_after_publication',
        'completed_fit_requirement': 12, 'prediction_block_requirement': 18,
        'observational_scope': 'already_inspected_development_months_not_unseen_holdout',
        'dashboard': False,
    }


def pairing_contract():
    return {
        'join_policy': 'exact_full_canonical_ID_order_no_inner_join_sort_repair_or_drop',
        'truth_columns': list(files.MEMBERSHIP_COLUMNS),
        'comparison_roles': ['inner_validation', 'outer_evaluation'],
        'control_blocks': 18, 'treatment_blocks': 18,
        'inner_pairing': 'same_fold_role_model_C_and_complete_truth',
        'outer_pairing': 'each_arm_independently_selected_C_may_differ_same_complete_truth',
        'constant_reference': 'exact_same_eligible_training_prior_each_role',
        'unknown_rows': 'present_in_all_score_blocks_with_nullable_y_and_finite_probability',
        'probabilities': 'all_rows_binary64_finite_0_to_1_including_unknown',
        'source_versions': 'one_bound_H60_roster_truth_and_frozen_control_manifest',
        'difference': 'treatment_minus_control_null_if_either_arm_null_never_fill_zero',
        'macro_AP': 'equal_months_only_if_both_arms_have_all_three_valid_months',
        'no_new_success_threshold_or_post_result_changes': True,
        'current_acceptance': 'frozen_control_and_pairing_rules_only_treatment_pending_no_training',
    }


def output_contract():
    return {
        'version': 'stage5_review_month_ablation_training_v1',
        'private_root': FUTURE_PRIVATE, 'public_report': FUTURE_REPORT,
        'private_files': list(FUTURE_FILES),
        'score_columns': list(control.SCORE_COLUMNS),
        'score_serialization': {'encoding': 'utf-8', 'newline': 'LF', 'index': False,
                                'nullable_y_C': 'empty_cell', 'float_format': '%.17g',
                                'clock_format': '%Y-%m-%d %H:%M:%S',
                                'readback': 'exact_cells_and_binary64_no_rounding'},
        'score_models': {'inner': ['constant_reference', 'logistic_candidate_C_0.1_1_10'],
                         'outer': ['logistic_selected', 'constant_reference']},
        'fit_audit_required': ['fold_role_C_fit_at', 'eligible_order_ids', 'scaler_mean_variance_scale_samples',
                               '32_output_columns', 'coefficients_intercept_classes', 'actual_fit_count'],
        'paired_acceptance_required': ['execution_specification', 'training_dispatcher_binding',
                                       'input_guard', 'control_manifest', 'treatment_file_digests',
                                       'all_18_blocks_same_ID_order_truth', 'unknown_coverage',
                                       'independent_treatment_C', 'constant_reference_equality'],
        'manifest_required': ['execution_specification', 'training_dispatcher_binding', 'input_guard',
                              'public_report', 'private_file_digests', 'completed_estimator_fits',
                              'paired_acceptance', 'no_training_replay'],
        'failure_receipt_required': ['execution_specification', 'phase', 'outer_fold', 'role', 'C',
                                     'completed_estimator_fits', 'exception_type'],
        'training_replay': 'any_existing_final_failure_or_unexpected_namespace_file_refuses_before_fit',
        'publication': 'all_output_paths_preflight_exact_readback_then_complete_success_only',
        'model_objects_persisted': False, 'control_files_copied_or_rewritten': False,
        'public_privacy': 'no_individual_ID_score_label_coefficient_private_digest_or_roster_hash',
        'preparation_creates_treatment_outputs': False,
    }


def _path(root, name, private=False):
    root = Path(root).resolve()
    path = root / name
    control.reject_output_aliases(path, root)
    resolved = files.safe_output(path, '' if private else name, root, private=private)
    if resolved.relative_to(root).as_posix() != name:
        raise ValueError('Output must retain its exact unaliased versioned path')
    for parent in resolved.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError('Output ancestor must be a directory')
        if parent == root:
            break
    return resolved


def output_paths(root=ROOT):
    return (_path(root, SPEC), _path(root, GUARD, True), _path(root, REPORT))


def require_future_outputs_absent(root=ROOT):
    public = _path(root, FUTURE_REPORT)
    directory = _path(root, FUTURE_PRIVATE, True)
    if public.exists() or (directory.exists() and (not directory.is_dir() or any(directory.iterdir()))):
        raise ValueError('Future training output namespace is occupied; no replay or overwrite allowed')
    for name in FUTURE_FILES:
        if _path(root, FUTURE_PRIVATE + '/' + name, True).exists():
            raise ValueError('Future training output already exists')
    return {'version': 'stage5_review_month_ablation_training_v1', 'namespace_empty': True,
            'output_files_created': 0, 'training_dispatcher_bound': False}


def make_specification(bundle, root=ROOT):
    root = Path(root).resolve()
    bundle.verify_stable()
    public = baseline_sources.merge_sources(bundle.public_sources,
        [files.descriptor(root / path, root) for path in CODE])
    if {item['path'] for item in public} & {item['path'] for item in bundle.private_sources}:
        raise ValueError('Public and private input bindings overlap')
    files.verify_sources(public + bundle.private_sources, root)
    return {
        'format_version': 1, 'role': 'frozen_month_ablation_execution_policy_no_training',
        'method_reference': files.descriptor(root / sources.method.SPEC, root),
        'pipeline_verification': files.descriptor(root / sources.PIPELINE_PROOF, root),
        'method_protocol_unchanged': deepcopy(bundle.method_spec['protocol']),
        'execution_plan': execution_plan(), 'same_ID_pairing': pairing_contract(),
        'output_contract': output_contract(), 'public_sources': public,
        'private_source_guard': {'path': GUARD, 'input_paths': [s['path'] for s in bundle.private_sources],
                                 'private_digests_public': False},
        'prepared_public_report': REPORT, 'actual_treatment_selected_C': None,
        'current_run': {'feature_build': 0, 'model_construction': 0, 'fit': 0, 'transform': 0,
                        'predict': 0, 'candidate_selection': 0, 'performance_metrics': 0, 'dashboard': 0},
        'historical_status_note': 'parent_this_run_and_implementation_status_are_unchanged_historical_metadata',
        'stage4': {'status': 'pending_data', 'daily_budget': 0.1, 'seeds': [11, 29, 42, 73, 101], 'modified': False},
    }


def _guard(specification_source, bundle):
    return {'format_version': 1, 'specification': specification_source,
            'private_sources': bundle.private_sources,
            'scope': 'existing_local_snapshot_not_original_ingestion_or_version_availability_proof'}


def _publish(payloads, bound, root):
    """Preflight every file and retract only newly-created exact bytes on failure."""
    paths = [path for path, _ in payloads]
    bound_paths = {(Path(root) / item['path']).resolve() for item in bound}
    if len(set(paths)) != len(paths) or any(path in bound_paths for path in paths):
        raise ValueError('Publication paths collide with each other or an input')
    for path, payload in payloads:
        files.immutable_preflight(path, payload)
    files.verify_sources(bound, root)
    created = []
    try:
        for path, payload in payloads:
            existed = path.exists()
            files.immutable_write(path, payload)
            if not existed:
                created.append((path, payload))
            if path.read_bytes() != payload:
                raise ValueError('Publication bytes failed exact readback')
            files.read_json(path)
        files.verify_sources(bound, root)
        require_future_outputs_absent(root)
    except Exception:
        for path, payload in reversed(created):
            if path.is_file() and path.read_bytes() == payload:
                path.unlink()
        raise


def freeze(bundle, root=ROOT):
    spec_path, guard_path, report_path = output_paths(root)
    require_future_outputs_absent(root)
    spec = make_specification(bundle, root)
    payload = files.json_bytes(spec)
    source = {'path': SPEC, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    # An existing accepted report must already bind this exact preparation version.
    if report_path.exists() and files.read_json(report_path).get('specification') != source:
        raise ValueError('Existing preflight report belongs to a different specification')
    bound = spec['public_sources'] + bundle.private_sources
    _publish([(spec_path, payload), (guard_path, files.json_bytes(_guard(source, bundle)))], bound, root)
    return spec


def verify_specification(bundle, root=ROOT):
    spec_path, guard_path, _ = output_paths(root)
    spec = files.read_json(spec_path)
    if spec != make_specification(bundle, root):
        raise ValueError('Execution policy, schema, program or source version changed')
    source = files.descriptor(spec_path, root)
    if files.read_json(guard_path) != _guard(source, bundle):
        raise ValueError('Private guard differs from the exact specification or input versions')
    bound = spec['public_sources'] + bundle.private_sources + [source, files.descriptor(guard_path, root)]
    files.verify_sources(bound, root)
    require_future_outputs_absent(root)
    return spec, source, bound


def role_acceptance(bundle):
    result = []
    for fold in files.OUTER_MONTHS:
        for role in baseline_sources.ROLES:
            block = bundle.role_block(fold, role)
            known = block.role_label_usable
            row = {'outer_fold': fold, 'role': role, 'orders': len(block),
                   'fit_at': str(block.fit_at.iloc[0]),
                   'observation_cutoff': str(block.observation_cutoff.iloc[0]),
                   'known_labels': int(known.sum()), 'unknown_labels': int((~known).sum()),
                   'known_low_1_2': int(block.loc[known, 'y'].eq(1).sum()),
                   'known_other_3_5': int(block.loc[known, 'y'].eq(0).sum())}
            if role in baseline_sources.QUERY_ROLES:
                safe = bundle.prediction_block(fold, role)
                if (list(safe.order_id) != list(block.order_id)
                        or not safe.loc[:, list(baseline_sources.FUTURE_QUERY_COLUMNS)].isna().all().all()):
                    raise ValueError('Prediction role must retain all IDs and mask all future truth')
                row['future_truth_columns_masked'] = len(baseline_sources.FUTURE_QUERY_COLUMNS)
            result.append(row)
    return result


def run(root=ROOT, specification_only=False):
    root = Path(root).resolve()
    with sources.forbid_model_execution() as counters:
        require_future_outputs_absent(root)
        bundle = sources.load_prepared_sources(root)
        if counters['forbidden_calls']:
            raise RuntimeError('A forbidden execution was attempted')
        if specification_only:
            result = freeze(bundle, root)
        else:
            spec, source, bound = verify_specification(bundle, root)
            roles = role_acceptance(bundle)
            result = {
                'format_version': 1, 'status': 'passed_month_ablation_source_role_control_preflight_no_training',
                'decision': 'execution_policy_and_pairing_gates_frozen_training_not_authorized',
                'specification': source, 'sources': spec['public_sources'], 'source_bundle': bundle.summary,
                'role_acceptance': roles, 'future_outputs': require_future_outputs_absent(root),
                'pair_acceptance': {'control': 'complete_frozen_score_metadata_accepted',
                                    'treatment': 'pending_not_trained', 'paired_effect': 'not_computed'},
                'actual_execution': dict(spec['current_run'], forbidden_calls=counters['forbidden_calls']),
                'actual_treatment_selected_C': None,
                'verification': {'public_bound_files': len(spec['public_sources']),
                                 'private_bound_files': len(bundle.private_sources),
                                 'complete_role_blocks': len(roles),
                                 'query_future_truth_mask_columns': 7,
                                 'control_scores_recomputed': False,
                                 'control_metrics_recomputed': False,
                                 'historical_ingestion_verified': False,
                                 'private_digests_public': False},
                'limitations': ['Treatment scores and actual paired acceptance remain pending training.',
                                'Future training dispatcher needs separate reviewed code and test bindings.',
                                'Existing event clocks are not original ingestion or score revision version proof.',
                                'Already inspected development months are not an unseen holdout.'],
                'stage4': spec['stage4'],
            }
            if counters['forbidden_calls']:
                raise RuntimeError('A forbidden execution was attempted')
            _publish([(output_paths(root)[2], files.json_bytes(result))], bound, root)
        if counters['forbidden_calls']:
            raise RuntimeError('A forbidden execution was attempted')
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    args = parser.parse_args(argv)
    result = run(specification_only=args.specification_only)
    print(result.get('status', 'frozen_month_ablation_execution_policy_no_training'))


if __name__ == '__main__':
    main()
