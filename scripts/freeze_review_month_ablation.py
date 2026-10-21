"""Freeze the purchase-month ablation contract and verify metadata; never train."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import sys

import pandas as pd

try:
    from scripts import audit_review_baseline_contract as baseline
    from scripts import freeze_review_dataset as files
except ModuleNotFoundError:
    import audit_review_baseline_contract as baseline
    import freeze_review_dataset as files

ROOT = Path(__file__).resolve().parents[1]
CODE = 'scripts/freeze_review_month_ablation.py'
TESTS = 'tests/test_review_month_ablation_contract.py'
SPEC = 'reports/stage5/review_month_ablation_specification.json'
REPORT = 'reports/stage5/review_month_ablation_contract_audit.json'
GUARD = '.runtime/stage5_review_month_ablation_v1/input_guard.json'
DIAG_SPEC = 'reports/stage5/review_score_diagnostic_specification.json'
DIAG_REPORT = 'reports/stage5/review_score_diagnostics.json'
DIAG_GUARD = '.runtime/stage5_review_score_diagnostics_v1/input_guard.json'
TRAIN_SPEC = 'reports/stage5/review_baseline_training_specification.json'
TRAIN_REPORT = 'reports/stage5/review_baseline_training.json'
TRAIN_PRIVATE = '.runtime/stage5_review_baseline_training_v1'
TRAIN_RECEIPT = '.runtime/stage5_offline_formal_execution_proof.json'
PINNED = {baseline.SPEC: '202de6045b7dcee7b00c068670fff44b5cac813a838d3d5ad15d620e18e721aa',
          TRAIN_SPEC: 'f9ddfd7c729b293b16cdb9202170765103df2a216a191438103b7349c92c285d',
          TRAIN_REPORT: '4bb7c8844872d81f58bfd85d32f087c0745e467997d394a46414e3e4fa7b0c0b',
          DIAG_SPEC: '5bdc471bd29f702bd2b6d06c185bfa1ba9d15d7261e0d56c7eeb67e9164e2428',
          DIAG_REPORT: 'a78ea05026d873dd6a70526ccd4be20ca0dd51a7896518b8df91fe62248e5bb2'}
ALLOWED_PATHS = ('features.categorical.purchase_month', 'features.one_hot.columns',
                 'features.output_columns', 'features.output_order', 'features.primary_order')


def merge_sources(*groups):
    merged = {}
    for group in groups:
        for source in group:
            item = {key: source[key] for key in ('path', 'bytes', 'sha256')}
            if item['path'] in merged and merged[item['path']] != item:
                raise ValueError('Conflicting source versions')
            merged[item['path']] = item
    return [merged[path] for path in sorted(merged)]


def protocol_diff(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            path = prefix + '.' + key if prefix else key
            if key not in after:
                result.append({'path': path, 'operation': 'remove', 'before': before[key]})
            elif key not in before:
                result.append({'path': path, 'operation': 'add', 'after': after[key]})
            else:
                result.extend(protocol_diff(before[key], after[key], path))
        return result
    if before != after:
        return [{'path': prefix, 'operation': 'replace', 'before': before, 'after': after}]
    return []


def ablation_protocol(parent):
    result = deepcopy(parent)
    features = result['features']
    if (features['primary_order'] != ['purchase_month', 'purchase_dayofweek', 'purchase_hour', 'approval_wait_hours']
            or features['categorical']['purchase_month'] != list(range(1, 13))
            or features['one_hot']['columns'] != 43 or features['output_columns'] != 44
            or features['output_order'] != ['month_1_through_12', 'dayofweek_0_through_6',
                                             'hour_0_through_23', 'scaled_approval_wait_hours']):
        raise ValueError('Parent four-column feature structure changed')
    features['primary_order'].remove('purchase_month')
    del features['categorical']['purchase_month']
    features['one_hot']['columns'] = 31
    features['output_columns'] = 32
    features['output_order'].remove('month_1_through_12')
    changes = protocol_diff(parent, result)
    if tuple(item['path'] for item in changes) != ALLOWED_PATHS:
        raise ValueError('Unexpected single-factor protocol change')
    return result, changes


def verify_ablation_protocol(parent, proposed):
    expected, changes = ablation_protocol(parent)
    if proposed != expected:
        raise ValueError('Only removing purchase_month and its twelve columns is allowed')
    return changes


def _digest(source):
    return {key: source[key] for key in ('bytes', 'sha256')}


def load_provenance(root=ROOT):
    """Hash old scores/fit audit only, retaining their original source chain."""
    root = Path(root)
    pinned = [files.descriptor(root / path, root) for path in PINNED]
    if any(item['sha256'] != PINNED[item['path']] for item in pinned):
        raise ValueError('A frozen public ancestor changed')
    parent = files.read_json(root / baseline.SPEC)
    baseline.verify_contract(parent, root / baseline.SPEC, root / baseline.GUARD, root)
    dataset_spec, dataset_audit, _, _ = baseline.old_provenance(root)
    diag_spec, diag_report, guard = (files.read_json(root / name) for name in (DIAG_SPEC, DIAG_REPORT, DIAG_GUARD))
    diag_source = files.descriptor(root / DIAG_SPEC, root)
    if (guard['specification'] != diag_source or diag_report['specification'] != diag_source
            or diag_report['sources'] != diag_spec['public_sources']
            or diag_report['protocol'] != diag_spec['protocol']
            or diag_report['status'] != 'completed_read_only_frozen_score_diagnostics'
            or [item['path'] for item in guard['private_sources']] != diag_spec['private_source_guard']['input_paths']):
        raise ValueError('Original diagnostic source guard differs')
    public = merge_sources(diag_spec['public_sources'], pinned)
    private = merge_sources(guard['private_sources'], [files.descriptor(root / DIAG_GUARD, root)])
    files.verify_sources(public + private, root)
    directory = root / TRAIN_PRIVATE
    if (directory / 'failure_receipt.json').exists():
        raise ValueError('Original training failure receipt exists')
    manifest = files.read_json(directory / 'manifest.json')
    receipt = files.read_json(root / TRAIN_RECEIPT)
    spec_source, report_source = (files.descriptor(root / name, root) for name in (TRAIN_SPEC, TRAIN_REPORT))
    if (manifest['specification'] != spec_source or manifest['public_report'] != report_source
            or manifest['input_guard'] != files.descriptor(directory / 'input_guard.json', root)
            or manifest['completed_estimator_fits'] != 12 or manifest['no_training_replay'] is not True
            or set(manifest['files']) != {'inner_scores.csv', 'outer_scores.csv', 'fit_audit.json'}):
        raise ValueError('Original training output manifest differs')
    for name, expected in manifest['files'].items():
        if _digest(files.descriptor(directory / name, root)) != expected:
            raise ValueError('Original score or fit-audit bytes changed')
    if (receipt['status'] != 'passed_one_formal_training_run' or receipt['real_classifier_fits'] != 12
            or receipt['additional_training_replays'] != 0
            or receipt['public_specification'] != _digest(spec_source)
            or receipt['public_report'] != _digest(report_source)
            or receipt['private_manifest'] != _digest(files.descriptor(directory / 'manifest.json', root))):
        raise ValueError('Original training receipt differs')
    return parent, dataset_spec, dataset_audit, public, private


def comparison_plan():
    return {'treatment': 'drop_purchase_month_only', 'control': 'existing_frozen_clock_four_scores',
            'control_refit_or_reselection': False,
            'treatment_C_selection': 'independent_original_inner_AP_rule_not_fixed_to_control_C',
            'pairing': 'same_source_version_fold_role_order_ID_canonical_order_and_role_truth',
            'query_rows': 'complete_roster_including_unknown', 'metric_rows': 'own_role_usable_labels_only',
            'paired_metric_null_policy': 'difference_null_if_either_arm_null_never_fill_zero',
            'paired_macro_support': 'compare_only_if_both_arms_have_all_three_valid_months',
            'future_outputs': ['original_monthly_metrics_and_coverage_for_each_arm',
                               'treatment_minus_frozen_control_monthly_metric_differences',
                               'macro_AP_only_when_all_three_months_valid',
                               'unchanged_eligible_training_constant_reference'],
            'stop_if_control_or_roster_version_differs': True,
            'future_treatment_inner_fits': 9, 'future_treatment_outer_refits': 3,
            'future_control_fits': 0, 'training_authorized_this_run': False,
            'new_performance_success_threshold': None, 'causal_or_unseen_test_claim': False,
            'post_result_additional_changes_or_cherry_picked_months': False}


def make_specification(provenance, root=ROOT):
    parent, dataset_spec, _, public, private = provenance
    protocol, changes = ablation_protocol(parent['protocol'])
    bound = merge_sources(public, [files.descriptor(Path(root) / name, root) for name in (CODE, TESTS)])
    definitions = parent['clock_definition_contract']['primary_expressions_AST_only']
    return {'format_version': 1, 'role': 'frozen_single_factor_ablation_contract_no_training',
            'hypothesis': 'test_dependency_on_purchase_month_under_sparse_mature_calendar_support_no_promised_gain',
            'protocol': protocol, 'allowed_protocol_changes': changes,
            'protocol_role_note': 'inherited_metadata_only_baseline_role_this_run_and_reference_policy_retained',
            'dataset_protocol_unchanged': dataset_spec['protocol'],
            'dataset_calendar_unchanged': parent['dataset_calendar_unchanged'],
            'clock_definitions_unchanged': {name: definitions[name] for name in protocol['features']['primary_order']},
            'software_versions_unchanged': parent['software_versions'],
            'comparison_plan': comparison_plan(), 'actual_selected_C': None,
            'actual_execution': {'feature_values_built': 0, 'model_imports': 0, 'model_instantiations': 0,
                                 'fits': 0, 'transforms': 0, 'predictions': 0, 'score_rows_parsed': 0,
                                 'metrics_computed': 0, 'candidate_selections': 0, 'dashboard': 0},
            'implementation_status': 'three_feature_builder_and_pipeline_not_implemented',
            'sources': bound, 'private_source_guard': {'path': GUARD,
                'input_paths': [item['path'] for item in private], 'private_digests_public': False},
            'public_audit': REPORT,
            'limitations': ['Previously inspected development months, not a new unseen holdout.',
                            'Sparse month support motivates an ablation, not proof of harm or expected improvement.',
                            'Unknown labels and original ingestion/version availability remain unresolved.']}


def output_paths(root):
    paths = []
    for name, private in ((SPEC, False), (GUARD, True), (REPORT, False)):
        path = Path(root) / name
        for candidate in (path, *path.parents):
            if candidate == Path(root):
                break
            if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
                raise ValueError('Output aliases are forbidden')
        paths.append(files.safe_output(path, '' if private else name, root, private=private))
    return paths


def freeze(provenance, root=ROOT):
    spec = make_specification(provenance, root)
    spec_path, guard_path, _ = output_paths(root)
    data = files.json_bytes(spec)
    source = {'path': SPEC, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    guard_data = files.json_bytes({'format_version': 1, 'specification': source,
                                  'private_sources': provenance[4], 'scope': 'local_snapshot_not_operational_as_of_proof'})
    for path, payload in ((spec_path, data), (guard_path, guard_data)):
        files.immutable_preflight(path, payload)
    bound = spec['sources'] + provenance[4]
    files.verify_sources(bound, root)
    files.immutable_write(spec_path, data)
    files.immutable_write(guard_path, guard_data)
    files.verify_sources(bound + [source], root)
    return spec


def verify_specification(provenance, root=ROOT):
    spec_path, guard_path, _ = output_paths(root)
    spec = files.read_json(spec_path)
    if spec != make_specification(provenance, root):
        raise ValueError('Frozen ablation contract or sources changed')
    verify_ablation_protocol(provenance[0]['protocol'], spec['protocol'])
    source, guard_source = files.descriptor(spec_path, root), files.descriptor(guard_path, root)
    guard = files.read_json(guard_path)
    expected_guard = {'format_version': 1, 'specification': source, 'private_sources': provenance[4],
                      'scope': 'local_snapshot_not_operational_as_of_proof'}
    if guard != expected_guard:
        raise ValueError('Private input guard differs from the frozen ablation contract')
    bound = spec['sources'] + provenance[4] + [source, guard_source]
    files.verify_sources(bound, root)
    return spec, source, bound


def audit_metadata(dataset_spec, dataset_audit, root=ROOT):
    columns = ['order_id', 'order_purchase_timestamp', 'order_approved_at']
    orders = pd.read_csv(Path(root) / files.ORDERS, usecols=columns, dtype='string')[columns]
    roster = baseline.raw_clock_roster(orders)
    labels = files.read_private_csv((Path(root) / files.PRIVATE / 'order_labels.csv').read_bytes(), files.LABEL_COLUMNS)
    membership = files.read_private_csv((Path(root) / files.PRIVATE / 'split_membership.csv').read_bytes(), files.MEMBERSHIP_COLUMNS)
    global_summary, folds = baseline.metadata_audit(roster, labels, membership, dataset_audit)
    if (len(orders) != dataset_audit['order_quality']['source_orders']
            or len(roster) != dataset_spec['expected_existing_cohort_orders']
            or [fold['calendar'] for fold in folds] != dataset_spec['calendar_split_plan']
            or any(fold['support'] != 'supported_for_future_offline_baseline_only' for fold in folds)):
        raise ValueError('Frozen dataset denominator, calendar or required class support differs')
    return {'raw_orders': len(orders), 'cohort_orders': len(roster), 'membership_rows': len(membership),
            'role_blocks': sum(len(fold['roles']) for fold in folds)}, global_summary, folds


def require_no_model_imports():
    if any(name == 'sklearn' or name.startswith('sklearn.') for name in sys.modules):
        raise RuntimeError('Specification-only command must not import model libraries')


def run(root=ROOT, specification_only=False):
    root = Path(root).resolve()
    require_no_model_imports()
    provenance = load_provenance(root)
    if specification_only:
        spec = freeze(provenance, root)
        require_no_model_imports()
        return spec
    spec, source, bound = verify_specification(provenance, root)
    summary, global_summary, folds = audit_metadata(provenance[1], provenance[2], root)
    require_no_model_imports()
    files.verify_sources(bound, root)
    result = {'format_version': 1, 'status': 'passed_month_ablation_contract_metadata_only',
              'decision': 'single_factor_contract_frozen_implementation_and_training_not_executed',
              'specification': source, 'sources': spec['sources'], 'protocol': spec['protocol'],
              'allowed_protocol_changes': spec['allowed_protocol_changes'], 'source_bundle': summary,
              'global_order_metadata': global_summary, 'nested_calendar_support': folds,
              'actual_execution': spec['actual_execution'], 'actual_selected_C': None,
              'verification': {'public_source_bindings_before_after': len(spec['sources']),
                               'private_source_bindings_before_after': len(provenance[4]),
                               'protocol_changed_paths': list(ALLOWED_PATHS), 'unchanged_other_protocol_fields': True,
                               'same_ID_complete_roles_and_label_cutoffs': True,
                               'old_scores_and_fit_audit_hash_only': True,
                               'future_treatment_selection_not_borrowed_from_control': True,
                               'historical_ingestion_verified': False, 'new_performance_claim': False},
              'limitations': spec['limitations']}
    data = files.json_bytes(result)
    path = output_paths(root)[2]
    files.immutable_preflight(path, data)
    existed = path.exists()
    try:
        files.immutable_write(path, data)
        if path.read_bytes() != data:
            raise ValueError('Audit readback mismatch')
        files.verify_sources(bound, root)
        require_no_model_imports()
    except Exception:
        if not existed and path.is_file() and path.read_bytes() == data:
            path.unlink()
        raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    args = parser.parse_args()
    result = run(specification_only=args.specification_only)
    print(result.get('status', 'frozen_purchase_month_ablation_specification_no_training'))


if __name__ == '__main__':
    main()
