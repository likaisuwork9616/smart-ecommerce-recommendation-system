"""Exclusive, fail-closed publication of the bound three-feature experiment."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

import numpy as np
import pandas as pd

from scripts import freeze_review_dataset as files
from scripts import prepare_review_month_ablation as preparation
from scripts import review_baseline_evaluation as evaluation
from scripts import review_baseline_pipeline as common
from scripts import review_month_ablation_pairing as pairing
from scripts import review_month_ablation_pipeline as pipeline
from scripts import run_review_baseline as codec

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = preparation.FUTURE_PRIVATE
REPORT = preparation.FUTURE_REPORT
PRIVATE_NAMES = preparation.FUTURE_FILES
REFERENCE_PATHS = {
    'execution_specification': preparation.SPEC,
    'training_dispatcher_binding': 'reports/stage5/review_month_ablation_dispatcher_specification.json',
    'input_guard': '.runtime/stage5_review_month_ablation_dispatcher_v1/input_guard.json',
    'control_manifest': codec.PRIVATE + '/manifest.json',
}
AUDIT_KEYS = ('format_version', 'fit_records', 'completed_estimator_fits',
              'inner_fits_completed', 'outer_fits_completed', 'model_objects_persisted')
FIT_KEYS = ('fit_sequence', 'outer_fold', 'role', 'C', 'fit_at', 'context_version',
            'eligible_order_ids', 'train_pool_order_ids', 'train_pool_orders',
            'unknown_excluded_from_fit', 'eligible_orders', 'eligible_low_1_2',
            'eligible_other_3_5', 'output_columns', 'scaler_mean', 'scaler_variance',
            'scaler_scale', 'scaler_samples', 'coefficient_values', 'intercept_values',
            'classes', 'seconds')
PUBLIC_RESULT_KEYS = ('outer_folds', 'fit_context_audits', 'aggregate_selected',
                      'aggregate_reference', 'paired_comparison', 'execution')
PAIR_KEYS = ('status', 'paired_blocks', 'score_blocks', 'score_rows_per_arm',
             'metrics_computed', 'candidate_selections', 'treatment_selection_recomputed',
             'independent_treatment_selection', 'constant_reference_equality', 'accepted_treatment_file_digests',
             'accepted_public_results_digest')
PAIR_BLOCK_KEYS = ('outer_fold', 'role', 'model', 'status', 'full_orders', 'known_labels',
                   'unknown_or_ineligible_labels', 'metadata_columns_compared',
                   'treatment_C', 'control_C', 'metrics_computed')
CONTEXT_KEYS = ('phase', 'outer_fold', 'role', 'C', 'completed_estimator_fits')
PUBLIC_SCHEMAS = {
    'fold': ('outer_fold', 'inner_training_support', 'inner_reference', 'inner_candidates',
             'selection', 'outer_selected', 'outer_reference'),
    'coverage': ('full_orders', 'known_labels', 'unknown_or_ineligible_labels',
                 'known_low_1_2', 'known_other_3_5', 'exclusive_label_states'),
    'evaluation': ('coverage', 'metrics'),
    'metrics': ('average_precision', 'roc_auc', 'brier', 'binary_log_loss', 'TP', 'FP', 'TN', 'FN', 'precision', 'recall'),
    'selection': ('selected_C', 'candidate_average_precision', 'maximum_average_precision',
                  'tie_absolute_tolerance', 'candidates_within_tolerance', 'tie_break',
                  'outer_labels_used', 'reference_in_selection'),
    'macro': ('macro_average_precision', 'valid_folds', 'required_folds', 'weighting',
              'pooled_average_precision_computed', 'independent_fold_confidence_interval'),
    'fit': ('fit_sequence', 'outer_fold', 'role', 'C', 'fit_at', 'train_pool_orders',
            'unknown_excluded_from_fit', 'eligible_orders', 'eligible_low_1_2', 'eligible_other_3_5',
            'output_columns', 'eligible_roster_and_scaler_sample_count_verified'),
    'comparison': ('scope', 'paired_groups', 'group_count', 'macro_average_precision', 'control_metrics',
                   'undefined_difference_policy', 'independent_fold_confidence_interval', 'new_success_threshold'),
    'comparison_group': ('outer_fold', 'role', 'model', 'treatment_C', 'control_C', 'coverage', 'treatment_minus_control'),
    'comparison_macro': ('treatment', 'control', 'treatment_minus_control', 'treatment_valid_folds',
                         'control_valid_folds', 'required_valid_folds_per_arm', 'weighting'),
    'execution': ('estimator_fits_completed', 'inner_candidates_evaluated', 'outer_refits_completed',
                  'reference_prior_computations', 'prediction_blocks_completed', 'score_rows_across_blocks',
                  'all_queries_scored_including_unknown', 'unknown_fitted_or_used_in_metrics',
                  'outer_labels_used_in_selection', 'control_fits', 'control_candidate_selections',
                  'control_metrics_recomputed', 'treatment_candidate_selections', 'automatic_retries', 'partial_success'),
}


def artifact_schema_contract():
    """Concrete versioned JSON field sets, in addition to the frozen CSV codec."""
    return {
        'version': 'stage5_review_month_ablation_artifacts_v1',
        'reference_paths': dict(REFERENCE_PATHS),
        'descriptor_keys': ['path', 'bytes', 'sha256'],
        'fit_audit_keys': list(AUDIT_KEYS), 'fit_record_keys': list(FIT_KEYS),
        'core_pairing_keys': list(PAIR_KEYS), 'paired_block_keys': list(PAIR_BLOCK_KEYS),
        'core_accepted_digest_keys': ['bytes', 'sha256'],
        'core_accepted_digest_files': ['inner_scores.csv', 'outer_scores.csv', 'fit_audit.json'],
        'core_accepted_public_results_digest_keys': ['bytes', 'sha256'],
        'paired_acceptance_keys': ['format_version', *REFERENCE_PATHS,
                                   'treatment_file_digests', 'acceptance'],
        'manifest_keys': ['format_version', *REFERENCE_PATHS, 'public_report', 'files',
                          'completed_estimator_fits', 'paired_acceptance', 'no_training_replay'],
        'failure_receipt_keys': ['format_version', 'status', *REFERENCE_PATHS,
                                 'execution_context', 'exception_type', 'automatic_retry'],
        'failure_context_keys': list(CONTEXT_KEYS),
        'public_report_keys': ['format_version', 'status', 'execution_specification',
                               'training_dispatcher_binding', 'results', 'private_outputs',
                               'verification', 'limitations', 'stage4'],
        'public_result_keys': list(PUBLIC_RESULT_KEYS),
        'public_nested_schemas': {key: list(value) for key, value in PUBLIC_SCHEMAS.items()},
        'private_files_on_success': [name for name in PRIVATE_NAMES if name != 'failure_receipt.json'],
        'failure_receipt_blocks_replay': True,
        'publication_order': ['inner_scores.csv', 'outer_scores.csv', 'fit_audit.json',
                              'paired_acceptance.json', 'manifest.json', REPORT],
        'rollback': 'only_newly_created_files_still_equal_to_owned_bytes',
        'partial_or_changed_owned_files': 'preserve_as_failure_evidence_and_refuse_replay',
        'receipt_owner': 'dispatcher_catches_and_records_failure_after_publication_rolls_back',
        'public_privacy': 'aggregate_allowlist_no_individual_values_or_private_hashes',
    }


def _exact_keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{name} has unexpected fields')


def _count(value, expected=None):
    if type(value) is not int or value < 0 or (expected is not None and value != expected):
        raise ValueError('Invalid exact nonnegative count')
    return value


def _references(references):
    _exact_keys(references, REFERENCE_PATHS, 'Artifact references')
    for key, expected_path in REFERENCE_PATHS.items():
        item = references[key]
        _exact_keys(item, ('path', 'bytes', 'sha256'), 'Source descriptor')
        if item['path'] != expected_path or not isinstance(item['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('Artifact references require exact versioned paths and SHA256')
        _count(item['bytes'])
    return deepcopy(references)


def _bound(sources, references=()):
    result = {}
    for item in [*sources, *references]:
        if item['path'] in result and result[item['path']] != item:
            raise ValueError('Conflicting source descriptors')
        result[item['path']] = deepcopy(item)
    return list(result.values())


def preflight(root=ROOT, bound_sources=()):
    """Check every final/failure path and all sources before the first fit."""
    root = Path(root).resolve()
    preparation.require_future_outputs_absent(root)
    paths = [preparation._path(root, REPORT)] + [
        preparation._path(root, PRIVATE + '/' + name, True) for name in PRIVATE_NAMES]
    bound = _bound(bound_sources)
    source_paths = {(root / item['path']).resolve() for item in bound}
    if len(set(paths)) != len(paths) or source_paths.intersection(paths):
        raise ValueError('An output collides with another output or bound input')
    files.verify_sources(bound, root)
    return bound


def _number_array(value, shape, *, nonnegative=False, positive=False):
    array = np.asarray(value)
    if array.dtype.kind not in 'fi' or array.shape != shape or not np.isfinite(array).all():
        raise ValueError('Invalid finite numeric fit diagnostics')
    if (nonnegative and (array < 0).any()) or (positive and (array <= 0).any()):
        raise ValueError('Invalid scaler diagnostics')


def _audit(audit, selected):
    _exact_keys(audit, AUDIT_KEYS, 'Private fit audit')
    _count(audit['format_version'], 1)
    if audit['model_objects_persisted'] is not False:
        raise ValueError('Fit audit version or model persistence differs')
    for key, count in [('completed_estimator_fits', 12), ('inner_fits_completed', 9), ('outer_fits_completed', 3)]:
        _count(audit[key], count)
    if not isinstance(audit['fit_records'], list) or len(audit['fit_records']) != 12:
        raise ValueError('All twelve private fit records are required')
    plans = [(fold, role, C) for fold in codec.FOLDS for role, C in
             [('inner_train_pool', C) for C in pairing.CANDIDATES] + [('outer_train_pool', selected[fold])]]
    for sequence, (record, (fold, role, C)) in enumerate(zip(audit['fit_records'], plans), 1):
        _exact_keys(record, FIT_KEYS, 'Private fit record')
        _count(record['fit_sequence'], sequence)
        if (record['outer_fold'], record['role'], record['C']) != (fold, role, C):
            raise ValueError('Fit sequence or independent selected C differs')
        pairing._candidate(record['C'])
        if record['fit_at'] != str(common._plan(fold, role)[2]):
            raise ValueError('Fit timestamp differs from frozen temporal plan')
        if not isinstance(record['context_version'], str) or not record['context_version']:
            raise ValueError('Fit context version must be present')
        for key in ('eligible_order_ids', 'train_pool_order_ids'):
            ids = record[key]
            if not isinstance(ids, list) or not ids or not all(isinstance(v, str) and v for v in ids) or len(ids) != len(set(ids)):
                raise ValueError('Fit IDs must be complete unique string rosters')
        eligible, pool = record['eligible_order_ids'], record['train_pool_order_ids']
        if eligible != [value for value in pool if value in set(eligible)]:
            raise ValueError('Eligible fit IDs must retain pool order')
        for key, count in [('eligible_orders', len(eligible)), ('train_pool_orders', len(pool)),
                           ('unknown_excluded_from_fit', len(pool) - len(eligible)), ('scaler_samples', len(eligible))]:
            _count(record[key], count)
        low, other = _count(record['eligible_low_1_2']), _count(record['eligible_other_3_5'])
        if not low or not other or low + other != len(eligible):
            raise ValueError('Fit diagnostics must retain both known classes')
        if record['output_columns'] != list(pipeline.OUTPUT_COLUMNS) or record['classes'] != [0, 1] or any(type(x) is not int for x in record['classes']):
            raise ValueError('Fit diagnostics require fixed32 columns and class order')
        _number_array(record['scaler_mean'], (1,))
        _number_array(record['scaler_variance'], (1,), nonnegative=True)
        _number_array(record['scaler_scale'], (1,), positive=True)
        _number_array(record['coefficient_values'], (1, 32))
        _number_array(record['intercept_values'], (1,))
        _number_array([record['seconds']], (1,), nonnegative=True)


def _acceptance(pair, frames, selected, audit):
    _exact_keys(pair, PAIR_KEYS, 'Paired acceptance')
    if (pair['status'] != 'passed_complete_same_ID_treatment_control_pairing'
            or pair['constant_reference_equality'] is not True
            or pair['treatment_selection_recomputed'] is not False):
        raise ValueError('Complete same-ID and constant-reference acceptance is required')
    for key, count in [('score_blocks', 18), ('score_rows_per_arm', sum(map(len, frames.values()))),
                       ('metrics_computed', 0), ('candidate_selections', 0)]:
        _count(pair[key], count)
    selection = pair['independent_treatment_selection']
    _exact_keys(selection, ('source', 'folds', 'control_C_used', 'selection_calls'), 'Independent selection')
    if selection['source'] != 'treatment_inner_validation_AP_only' or selection['control_C_used'] is not False:
        raise ValueError('Treatment must independently select C')
    _count(selection['selection_calls'], 3)
    if not isinstance(selection['folds'], list) or [x['outer_fold'] for x in selection['folds']] != list(codec.FOLDS):
        raise ValueError('Independent selection evidence must retain all three folds')
    if any(x['selected_C'] != selected[x['outer_fold']] or x['outer_labels_used'] is not False or x['reference_in_selection'] is not False for x in selection['folds']):
        raise ValueError('Independent selection evidence differs from treatment results')
    if not isinstance(pair['paired_blocks'], list) or len(pair['paired_blocks']) != 18:
        raise ValueError('All eighteen paired blocks are required')
    expected = [(fold, role, model, C) for role in pairing.ROLES for fold in codec.FOLDS
                for model, C in pairing._plans(role, selected[fold])]
    consumed = {name: pd.Series(False, index=frame.index) for name, frame in frames.items()}
    for entry, (fold, role, model, C) in zip(pair['paired_blocks'], expected):
        _exact_keys(entry, PAIR_BLOCK_KEYS, 'Paired block')
        if ((entry['outer_fold'], entry['role'], entry['model'], entry['treatment_C']) != (fold, role, model, C)
                or entry['status'] != 'passed_same_ID_role_truth_pairing'):
            raise ValueError('Paired block identity differs')
        _count(entry['metadata_columns_compared'], len(files.MEMBERSHIP_COLUMNS))
        _count(entry['metrics_computed'], 0)
        if model == 'constant_reference':
            if entry['control_C'] is not None:
                raise ValueError('Constant reference must retain null control C')
        else:
            pairing._candidate(entry['treatment_C'])
            pairing._candidate(entry['control_C'])
            if model == 'logistic_candidate' and entry['control_C'] != C:
                raise ValueError('Inner paired C differs')
        name = 'inner_scores.csv' if role == 'inner_validation' else 'outer_scores.csv'
        frame = frames[name]
        mask = pairing._select(frame, fold, role, model, C)
        block = frame.loc[mask]
        if (consumed[name] & mask).any() or block.empty:
            raise ValueError('Missing or overlapping score blocks')
        train_role = 'inner_train_pool' if role == 'inner_validation' else 'outer_train_pool'
        fitted = next(record for record in audit['fit_records'] if record['outer_fold'] == fold and record['role'] == train_role)
        prior = fitted['eligible_low_1_2'] / fitted['eligible_orders'] if model == 'constant_reference' else None
        support = pairing.validate_score_block(block, block.loc[:, list(files.MEMBERSHIP_COLUMNS)], model, C, prior=prior)
        for key, value in support.items():
            _count(entry[key], value)
        consumed[name] |= mask
    if not all(mask.all() for mask in consumed.values()):
        raise ValueError('Unpaired score rows cannot be published')


def _public_schema(public, audit, pair):
    """Reject extra nested fields rather than relying on a privacy denylist."""
    def schema(value, name):
        _exact_keys(value, PUBLIC_SCHEMAS[name], 'Public ' + name)

    def metrics(value):
        schema(value, 'metrics')
        for number in value.values():
            if number is not None and (type(number) not in (int, float) or not np.isfinite(number)):
                raise ValueError('Public metrics must be nullable finite numbers')

    def coverage(value):
        schema(value, 'coverage')
        _exact_keys(value['exclusive_label_states'], evaluation.STATES, 'Public label counts')
        for key, count in value.items():
            if key != 'exclusive_label_states':
                _count(count)
        for count in value['exclusive_label_states'].values():
            _count(count)

    def evaluated(value):
        schema(value, 'evaluation')
        coverage(value['coverage'])
        metrics(value['metrics'])

    for fold, proof in zip(public['outer_folds'], pair['independent_treatment_selection']['folds']):
        schema(fold, 'fold')
        coverage(fold['inner_training_support'])
        for key in ('inner_reference', 'outer_selected', 'outer_reference'):
            evaluated(fold[key])
        candidates = fold['inner_candidates']
        if not isinstance(candidates, list) or [x['C'] for x in candidates] != list(pairing.CANDIDATES):
            raise ValueError('Public candidates must retain all three fixed Cs')
        for candidate in candidates:
            _exact_keys(candidate, ('C', 'evaluation'), 'Public candidate')
            pairing._candidate(candidate['C'])
            evaluated(candidate['evaluation'])
        selection = fold['selection']
        schema(selection, 'selection')
        if proof != {'outer_fold': fold['outer_fold'], **selection}:
            raise ValueError('Public and private independent selection evidence differ')
        expected_AP = [{'C': x['C'], 'average_precision': x['evaluation']['metrics']['average_precision']} for x in candidates]
        if selection['candidate_average_precision'] != expected_AP:
            raise ValueError('Selection AP evidence differs from candidate evaluations')
        for candidate in selection['candidate_average_precision']:
            _exact_keys(candidate, ('C', 'average_precision'), 'Selection AP')
            pairing._candidate(candidate['C'])
        values = [x['average_precision'] for x in expected_AP]
        if any(type(x) not in (float, int) or not np.isfinite(x) or not 0 <= x <= 1 for x in values):
            raise ValueError('Selection AP must be finite and defined for every candidate')
        maximum = max(values)
        within = [x['C'] for x in expected_AP if maximum - x['average_precision'] <= evaluation.TIE_TOLERANCE]
        if (selection['maximum_average_precision'] != maximum
                or selection['tie_absolute_tolerance'] != evaluation.TIE_TOLERANCE
                or selection['candidates_within_tolerance'] != within
                or selection['selected_C'] != min(within) or selection['tie_break'] != 'smallest_C'
                or selection['outer_labels_used'] is not False or selection['reference_in_selection'] is not False):
            raise ValueError('Selection proof does not satisfy the frozen AP rule')
    if not isinstance(public['fit_context_audits'], list) or len(public['fit_context_audits']) != 12:
        raise ValueError('Public audit requires exactly twelve fit summaries')
    for public_fit, private_fit in zip(public['fit_context_audits'], audit['fit_records']):
        schema(public_fit, 'fit')
        expected = {key: private_fit[key] for key in PUBLIC_SCHEMAS['fit']
                    if key not in ('output_columns', 'eligible_roster_and_scaler_sample_count_verified')}
        expected.update(output_columns=32, eligible_roster_and_scaler_sample_count_verified=True)
        if public_fit != expected:
            raise ValueError('Public and private fit diagnostics differ')
    for key in ('aggregate_selected', 'aggregate_reference'):
        schema(public[key], 'macro')
    comparison = public['paired_comparison']
    schema(comparison, 'comparison')
    schema(comparison['macro_average_precision'], 'comparison_macro')
    _count(comparison['group_count'], 18)
    if not isinstance(comparison['paired_groups'], list) or len(comparison['paired_groups']) != 18:
        raise ValueError('Every paired aggregate group must be present')
    for group in comparison['paired_groups']:
        schema(group, 'comparison_group')
        coverage(group['coverage'])
        metrics(group['treatment_minus_control'])
    schema(public['execution'], 'execution')
    for key, count in [('estimator_fits_completed', 12), ('inner_candidates_evaluated', 9),
                       ('outer_refits_completed', 3), ('reference_prior_computations', 6),
                       ('prediction_blocks_completed', 18), ('control_fits', 0),
                       ('control_candidate_selections', 0), ('control_metrics_recomputed', 0),
                       ('treatment_candidate_selections', 3), ('automatic_retries', 0)]:
        _count(public['execution'][key], count)
    for key, value in [('all_queries_scored_including_unknown', True), ('unknown_fitted_or_used_in_metrics', False),
                       ('outer_labels_used_in_selection', False), ('partial_success', False)]:
        if public['execution'][key] is not value:
            raise ValueError('Execution evidence differs from frozen policy')


def _public_guard(public, references, audit, frames):
    _exact_keys(public, PUBLIC_RESULT_KEYS, 'Public aggregate results')
    forbidden_keys = {'order_id', 'order_ids', 'eligible_order_ids', 'train_pool_order_ids',
                      'coefficient_values', 'intercept_values', 'probability_low_1_2', 'y',
                      'sha256', 'roster_hash', 'private_digests', 'scaler_mean', 'scaler_variance',
                      'scaler_scale', 'context_version'}
    private_values = {item['sha256'] for key, item in references.items() if key in ('input_guard', 'control_manifest')}
    private_values.update(value for record in audit['fit_records'] for value in record['train_pool_order_ids'])
    private_values.update(value for frame in frames.values() for value in frame.order_id)

    def visit(value):
        if isinstance(value, dict):
            if forbidden_keys.intersection(value):
                raise ValueError('Private details cannot appear in public results')
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value in private_values:
            raise ValueError('Private identifiers or digests cannot appear in public results')
    visit(public)
    # Serialization also rejects NaN, infinities, estimator objects and non-JSON values.
    files.json_bytes(public)


def _descriptor(path, payload):
    return {'path': path, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}


def _write_exclusive(path, payload, created):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        created.append((path, payload))
        stream.write(payload)


def _verify_written_namespace(created, root):
    expected = {path: data for path, data in created}
    private_directory = preparation._path(root, PRIVATE, True)
    observed = set(private_directory.iterdir()) if private_directory.exists() else set()
    if observed != {path for path in expected if path.parent == private_directory}:
        raise ValueError('Unexpected private namespace entry appeared during publication')
    report = preparation._path(root, REPORT)
    if report.exists() != (report in expected):
        raise ValueError('Unexpected public artifact appeared during publication')
    for path, data in expected.items():
        preparation._path(root, path.relative_to(root).as_posix(), path != report)
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError('Published artifact changed during publication')


def publish(execution, references, *, verify_sources, bound_sources=(), root=ROOT):
    """Publish complete success, or retract only our unchanged newly written bytes."""
    root = Path(root).resolve()
    references = _references(references)
    bound = _bound(bound_sources, references.values())
    preflight(root, bound)
    verify_sources()
    if not isinstance(execution, tuple) or len(execution) != 5:
        raise ValueError('Complete five-part training execution is required')
    public, inner, outer, audit, pair = execution
    frames = {'inner_scores.csv': inner, 'outer_scores.csv': outer}
    _exact_keys(public, PUBLIC_RESULT_KEYS, 'Public aggregate results')
    folds = public['outer_folds']
    if not isinstance(folds, list) or [row['outer_fold'] for row in folds] != list(codec.FOLDS):
        raise ValueError('Every development fold must be completed before publication')
    selected = {row['outer_fold']: pairing._candidate(row['selection']['selected_C']) for row in folds}
    _count(public['execution']['estimator_fits_completed'], 12)
    _count(public['execution']['score_rows_across_blocks'], len(inner) + len(outer))
    _audit(audit, selected)
    _acceptance(pair, frames, selected, audit)
    _public_schema(public, audit, pair)
    _public_guard(public, references, audit, frames)
    public_results_bytes = files.json_bytes(public)
    accepted_public = {'bytes': len(public_results_bytes), 'sha256': hashlib.sha256(public_results_bytes).hexdigest()}
    if pair['accepted_public_results_digest'] != accepted_public:
        raise ValueError('Public aggregate results changed after complete same-ID acceptance')
    payloads = {name: codec._csv_bytes(frame) for name, frame in frames.items()}
    payloads['fit_audit.json'] = files.json_bytes(audit)
    _exact_keys(pair['accepted_treatment_file_digests'], payloads, 'Accepted treatment file digests')
    for name, data in payloads.items():
        expected = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if pair['accepted_treatment_file_digests'][name] != expected:
            raise ValueError('Treatment artifact bytes changed after complete same-ID acceptance')
    checks = {name: codec.verify_score_bytes(frame, payloads[name]) for name, frame in frames.items()}
    treatment_digests = {name: _descriptor(PRIVATE + '/' + name, data) for name, data in payloads.items()}
    acceptance = {'format_version': 1, **references, 'treatment_file_digests': treatment_digests,
                  'acceptance': deepcopy(pair)}
    payloads['paired_acceptance.json'] = files.json_bytes(acceptance)
    private_outputs = {name: {'path': PRIVATE + '/' + name} for name in PRIVATE_NAMES if name != 'failure_receipt.json'}
    for name, frame in frames.items():
        private_outputs[name].update(rows=len(frame), columns=list(codec.SCORE_COLUMNS))
    result = {
        'format_version': 1, 'status': 'completed_real_offline_month_ablation',
        'execution_specification': references['execution_specification'],
        'training_dispatcher_binding': references['training_dispatcher_binding'],
        'results': deepcopy(public), 'private_outputs': private_outputs,
        'verification': {'score_csv_exact_readback': checks, 'private_digests_public': False,
                         'completed_estimator_fits': 12, 'paired_blocks': 18,
                         'control_fits': 0, 'control_scores_recomputed': False,
                         'new_unseen_holdout_claim': False, 'dashboard': False},
        'limitations': ['Already inspected development months are not an unseen holdout.',
                        'Known-label metrics exclude unknown labels; every query still has a score.',
                        'Original ingestion, version timestamps and upstream completeness remain unverified.'],
        'stage4': {'status': 'pending_data', 'daily_budget': 0.1, 'seeds': [11, 29, 42, 73, 101], 'modified': False},
    }
    report_bytes = files.json_bytes(result)
    manifest = {'format_version': 1, **references, 'public_report': _descriptor(REPORT, report_bytes),
                'files': {name: _descriptor(PRIVATE + '/' + name, data) for name, data in payloads.items()},
                'completed_estimator_fits': 12,
                'paired_acceptance': _descriptor(PRIVATE + '/paired_acceptance.json', payloads['paired_acceptance.json']),
                'no_training_replay': True}
    payloads['manifest.json'] = files.json_bytes(manifest)
    targets = [(preparation._path(root, PRIVATE + '/' + name, True), data) for name, data in payloads.items()]
    targets.append((preparation._path(root, REPORT), report_bytes))
    # Recheck immediately before writes; no idempotent publication or same-byte replay.
    preflight(root, bound)
    verify_sources()
    created = []
    try:
        for path, data in targets:
            _verify_written_namespace(created, root)
            if path.name == Path(REPORT).name:
                files.verify_sources(bound, root)
                verify_sources()
            _write_exclusive(path, data, created)
            if path.read_bytes() != data:
                raise ValueError('Published bytes failed exact readback')
            if path.suffix == '.csv':
                codec.verify_score_bytes(frames[path.name], path.read_bytes())
            elif files.read_json(path) != files.json.loads(data):
                raise ValueError('Published JSON failed exact readback')
        files.verify_sources(bound, root)
        verify_sources()
        _verify_written_namespace(created, root)
    except Exception:
        for path, data in reversed(created):
            # A partial write or concurrent change is retained as failure evidence.
            if path.is_file() and not path.is_symlink() and path.read_bytes() == data:
                path.unlink()
        raise
    return result


def write_failure_receipt(context, exception_type, references, *, root=ROOT):
    """Record one private failure without copying exception text or retrying."""
    root = Path(root).resolve()
    references = _references(references)
    _exact_keys(context, CONTEXT_KEYS, 'Failure context')
    if (not isinstance(context['phase'], str) or not re.fullmatch(r'[a-z][a-z0-9_]*', context['phase'])
            or context['outer_fold'] not in (None, *codec.FOLDS)
            or context['role'] not in (None, 'inner_train_pool', 'inner_validation', 'outer_train_pool', 'outer_evaluation')):
        raise ValueError('Failure context must contain only bounded execution metadata')
    if context['C'] is not None:
        pairing._candidate(context['C'])
    if _count(context['completed_estimator_fits']) > 12:
        raise ValueError('Failure count exceeds one complete run')
    if not isinstance(exception_type, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', exception_type):
        raise ValueError('Only the exception class name is recorded')
    path = preparation._path(root, PRIVATE + '/failure_receipt.json', True)
    receipt = {'format_version': 1, 'status': 'stopped_no_retry_no_partial_success', **references,
               'execution_context': deepcopy(context), 'exception_type': exception_type, 'automatic_retry': False}
    data = files.json_bytes(receipt)
    _write_exclusive(path, data, [])
    if path.read_bytes() != data or files.read_json(path) != receipt:
        raise ValueError('Failure receipt failed exact readback')
    return receipt
