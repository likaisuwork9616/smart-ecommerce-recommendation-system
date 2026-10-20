"""Run the frozen offline clock-four baseline once, behind verified source gates."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

try:
    from scripts import freeze_review_dataset as files
    from scripts import review_baseline_evaluation as evaluation
    from scripts.review_baseline_pipeline import GuardedReviewBaseline
except ModuleNotFoundError:
    import freeze_review_dataset as files
    import review_baseline_evaluation as evaluation
    from review_baseline_pipeline import GuardedReviewBaseline

ROOT = Path(__file__).resolve().parents[1]
CODE = 'scripts/run_review_baseline.py'
EVALUATION = 'scripts/review_baseline_evaluation.py'
LOADER = 'scripts/review_baseline_sources.py'
TESTS = 'tests/test_review_baseline_training.py'
SOURCE_TESTS = 'tests/test_review_baseline_sources.py'
PARENT = 'reports/stage5/review_baseline_specification.json'
PARENT_SHA = '202de6045b7dcee7b00c068670fff44b5cac813a838d3d5ad15d620e18e721aa'
SPEC = 'reports/stage5/review_baseline_training_specification.json'
REPORT = 'reports/stage5/review_baseline_training.json'
PRIVATE = '.runtime/stage5_review_baseline_training_v1'
GUARD = PRIVATE + '/input_guard.json'
FOLDS = ('2017-12', '2018-02', '2018-04')
SCORE_COLUMNS = ['outer_fold', 'role', 'model', 'C', 'fit_at', 'order_id', 'prediction_time',
                 'window_deadline', 'observation_cutoff', 'horizon_complete', 'label_state',
                 'role_label_usable', 'y', 'first_visible_answer_at', 'probability_low_1_2']
OUTPUT_NAMES = ('inner_scores.csv', 'outer_scores.csv', 'fit_audit.json', 'manifest.json')
FAILURE_NAME = 'failure_receipt.json'


class TrainingStopped(RuntimeError):
    def __init__(self, context, cause):
        self.context = dict(context)
        self.cause_type = type(cause).__name__
        super().__init__('Training stopped without fallback: ' + self.cause_type)


def execution_plan():
    return {'outer_folds': list(FOLDS), 'C_candidates': list(evaluation.CANDIDATES),
            'inner_fits_per_fold': 3, 'outer_fits_per_fold': 1, 'total_estimator_fits': 12,
            'selection': 'inner_validation_AP_max_tolerance_1e-12_smallest_C',
            'reference': 'eligible_training_unsmoothed_class_prior_not_a_candidate',
            'query_scoring': 'all_orders_including_unknown', 'metric_rows': 'usable_labels_only',
            'candidate_failure': 'stop_fold_and_run_no_candidate_removal_or_fallback',
            'failure_receipt': 'private_fold_role_C_phase_completed_fit_count_no_partial_public_report',
            'preprocessing': 'new_candidate_and_context_instance_eligible_training_rows_only',
            'earlier_outer_results_change_later_selection': False,
            'automatic_retry_or_replay_training': False,
            'data_role': 'already_inspected_nested_rolling_development_not_unseen_holdout',
            'stage4': 'pending_data_daily_10_percent_five_seeds_unchanged',
            'dashboard': False}


def load_sources(root=ROOT):
    try:
        from scripts.review_baseline_sources import load_verified_sources
    except ModuleNotFoundError:
        from review_baseline_sources import load_verified_sources
    return load_verified_sources(root=root)


def reject_output_aliases(path, root=ROOT):
    root, path = Path(root).absolute(), Path(path).absolute()
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise ValueError('Output paths cannot use symlink or junction aliases')


def merged_sources(*groups):
    merged = {}
    for group in groups:
        for item in group:
            source = {name: item[name] for name in ('path', 'bytes', 'sha256')}
            if source['path'] in merged and merged[source['path']] != source:
                raise ValueError('Conflicting source descriptors')
            merged[source['path']] = source
    return [merged[path] for path in sorted(merged)]


def make_specification(bundle, root=ROOT):
    root = Path(root)
    bundle.verify_stable()
    parent = files.descriptor(root / PARENT, root)
    if parent['sha256'] != PARENT_SHA:
        raise ValueError('Parent baseline method specification changed')
    sources = merged_sources(bundle.public_sources, [parent], [files.descriptor(root / path, root)
                              for path in (CODE, EVALUATION, LOADER, TESTS, SOURCE_TESTS)])
    files.verify_sources(sources, root)
    return {'format_version': 1, 'role': 'frozen_real_offline_minimal_baseline_execution',
            'method_reference': parent, 'execution_plan': execution_plan(), 'public_sources': sources,
            'private_source_guard': {'default_path': GUARD, 'input_paths': [item['path'] for item in bundle.private_sources],
                                     'private_digests_public': False},
            'private_output_default_root': PRIVATE, 'public_output': REPORT,
            'privacy': {'individual_scores_ids_labels_private_only': True,
                        'private_output_digest_or_roster_hash_public': False},
            'training_replay_policy': 'refuse_if_any_final_output_exists_before_fit'}


def freeze_specification(bundle, spec_path, guard_path, root=ROOT):
    root = Path(root)
    reject_output_aliases(spec_path, root)
    reject_output_aliases(guard_path, root)
    spec_path = files.safe_output(spec_path, SPEC, root)
    guard_path = files.safe_output(guard_path, '', root, private=True)
    spec = make_specification(bundle, root)
    data = files.json_bytes(spec)
    spec_source = {'path': spec_path.relative_to(root.resolve()).as_posix(), 'bytes': len(data),
                   'sha256': hashlib.sha256(data).hexdigest()}
    guard = {'format_version': 1, 'specification': spec_source,
             'private_sources': bundle.private_sources,
             'scope': 'frozen_local_sources_not_original_operational_ingestion_proof'}
    paths = {(root / item['path']).resolve() for item in spec['public_sources'] + bundle.private_sources}
    if spec_path == guard_path or spec_path in paths or guard_path in paths:
        raise ValueError('Specification/guard collides with existing source')
    files.immutable_preflight(spec_path, data)
    files.immutable_preflight(guard_path, files.json_bytes(guard))
    bundle.verify_stable()
    files.verify_sources(spec['public_sources'], root)
    files.immutable_write(spec_path, data)
    files.immutable_write(guard_path, files.json_bytes(guard))
    files.verify_sources(spec['public_sources'] + bundle.private_sources + [spec_source], root)
    bundle.verify_stable()
    return spec


def verify_execution_specification(bundle, spec, spec_path, guard_path, root=ROOT):
    root = Path(root)
    if spec != make_specification(bundle, root):
        raise ValueError('Frozen execution plan, code or source guard changed')
    source = files.descriptor(spec_path, root)
    guard = files.read_json(guard_path)
    if guard['specification'] != source or guard['private_sources'] != bundle.private_sources:
        raise ValueError('Private guard differs from actual run specification or source versions')
    guard_source = files.descriptor(guard_path, root)
    files.verify_sources(spec['public_sources'] + guard['private_sources'] + [source, guard_source], root)
    bundle.verify_stable()
    return source, guard_source


def _private_diagnostics(model, block, fold, role, C, seconds):
    support = evaluation.require_both_classes(block)
    state = model.audit_state()
    ids = tuple(block.loc[block.role_label_usable, 'order_id'])
    if state['eligible_order_ids'] != ids or state['scaler_samples'] != len(ids):
        raise ValueError('Actual preprocessing fit roster differs from eligible historical labels')
    if len(state['output_columns']) != 44 or state['state'] != 'FITTED':
        raise ValueError('Actual fitted pipeline violates fixed44/successful-state contract')
    private = {'outer_fold': fold, 'role': role, 'C': float(C), 'fit_at': str(state['fit_context'][2]),
               'eligible_order_ids': list(ids), 'train_pool_orders': len(block),
               'unknown_excluded_from_fit': support['unknown_or_ineligible_labels'],
               'eligible_orders': len(ids), 'eligible_low_1_2': support['known_low_1_2'],
               'eligible_other_3_5': support['known_other_3_5'], 'output_columns': list(state['output_columns']),
               'scaler_mean': state['scaler_mean'].tolist(), 'scaler_variance': state['scaler_variance'].tolist(),
               'scaler_scale': state['scaler_scale'].tolist(), 'scaler_samples': state['scaler_samples'],
               'coefficient_values': state['coefficient_values'].tolist(),
               'intercept_values': state['intercept_values'].tolist(), 'classes': state['classes'].tolist(),
               'seconds': seconds}
    public = {key: private[key] for key in ('outer_fold', 'role', 'C', 'fit_at', 'train_pool_orders',
                                           'unknown_excluded_from_fit', 'eligible_orders',
                                           'eligible_low_1_2', 'eligible_other_3_5')}
    public.update({'output_columns': 44, 'eligible_roster_and_scaler_sample_count_verified': True})
    return private, public


def _ledger(block, probabilities, model_name, C):
    evaluation.evaluate_role(probabilities, block)
    result = block.loc[:, list(files.MEMBERSHIP_COLUMNS)].copy()
    result.insert(2, 'model', model_name)
    result.insert(3, 'C', pd.Series([C] * len(result), index=result.index, dtype='Float64'))
    result['probability_low_1_2'] = probabilities.to_numpy(dtype='float64')
    return result.loc[:, SCORE_COLUMNS]


def _execute_training(bundle, spec, emit, tracker, verify_sources):
    """One fresh 12-fit execution; tests supply only a synthetic verified bundle."""
    if (spec['execution_plan'] != execution_plan()
            or spec['method_reference']['sha256'] != PARENT_SHA):
        raise ValueError('Training requires the frozen execution and parent method')
    verify_sources()
    fit_count, private_fits, public_fits, inner_ledgers, outer_ledgers, folds = 0, [], [], [], [], []
    for fold in FOLDS:
        tracker.update({'outer_fold': fold, 'role': 'inner_train_pool', 'C': None, 'phase': 'inner_support'})
        inner_train = bundle.role_block(fold, 'inner_train_pool')
        inner_query = bundle.role_block(fold, 'inner_validation')
        safe_inner_query = bundle.prediction_block(fold, 'inner_validation')
        inner_support = evaluation.require_both_classes(inner_train)
        evaluation.require_both_classes(inner_query)
        inner_prior = evaluation.constant_reference_probability(inner_train)
        inner_reference = pd.Series(inner_prior, index=pd.Index(inner_query.order_id, name='order_id'), dtype='float64')
        inner_reference_evaluation = evaluation.evaluate_role(inner_reference, inner_query)
        inner_ledgers.append(_ledger(inner_query, inner_reference, 'constant_reference', pd.NA))
        candidates, candidate_ap = [], {}
        for C in evaluation.CANDIDATES:
            tracker.update({'role': 'inner_train_pool', 'C': float(C), 'phase': 'inner_source_before_fit'})
            verify_sources()
            tick = time.perf_counter()
            model = GuardedReviewBaseline(C, context=bundle.context)
            tracker['phase'] = 'inner_fit'
            model.fit_orders(bundle.raw_orders, inner_train, outer_fold=fold, role='inner_train_pool')
            tracker['completed_estimator_fits'] += 1
            tracker['phase'] = 'inner_prediction_and_evaluation'
            predictions = model.predict_orders(bundle.raw_orders, safe_inner_query,
                                                outer_fold=fold, role='inner_validation')
            verify_sources()
            metrics = evaluation.evaluate_role(predictions, inner_query)
            AP = metrics['metrics']['average_precision']
            if AP is None or not np.isfinite(AP):
                raise ValueError('Any failed/nonfinite inner AP stops the fold without removing a candidate')
            private, public = _private_diagnostics(model, inner_train, fold, 'inner_train_pool', C,
                                                    time.perf_counter() - tick)
            private_fits.append(private)
            public_fits.append(public)
            fit_count += 1
            candidate_ap[C] = AP
            candidates.append({'C': float(C), 'evaluation': metrics})
            inner_ledgers.append(_ledger(inner_query, predictions, 'logistic_candidate', C))
            emit({'phase': 'inner_fit_complete', 'outer_fold': fold, 'C': float(C),
                  'completed_estimator_fits': fit_count, 'eligible_orders': inner_support['known_labels']})
        selection = evaluation.select_candidate(candidate_ap)
        chosen = selection['selected_C']
        tracker.update({'role': 'outer_train_pool', 'C': chosen, 'phase': 'outer_support'})
        # Outer outcomes have not participated in candidate evaluation or selection.
        outer_train = bundle.role_block(fold, 'outer_train_pool')
        evaluation.require_both_classes(outer_train)
        outer_query = bundle.role_block(fold, 'outer_evaluation')
        safe_outer_query = bundle.prediction_block(fold, 'outer_evaluation')
        outer_prior = evaluation.constant_reference_probability(outer_train)
        outer_reference = pd.Series(outer_prior, index=pd.Index(outer_query.order_id, name='order_id'), dtype='float64')
        verify_sources()
        tick = time.perf_counter()
        outer_model = GuardedReviewBaseline(chosen, context=bundle.context)
        tracker['phase'] = 'outer_fit'
        outer_model.fit_orders(bundle.raw_orders, outer_train, outer_fold=fold, role='outer_train_pool')
        tracker['completed_estimator_fits'] += 1
        tracker['phase'] = 'outer_prediction_and_evaluation'
        outer_predictions = outer_model.predict_orders(bundle.raw_orders, safe_outer_query,
                                                        outer_fold=fold, role='outer_evaluation')
        verify_sources()
        outer_evaluation = evaluation.evaluate_role(outer_predictions, outer_query)
        reference_evaluation = evaluation.evaluate_role(outer_reference, outer_query)
        private, public = _private_diagnostics(outer_model, outer_train, fold, 'outer_train_pool', chosen,
                                                time.perf_counter() - tick)
        private_fits.append(private)
        public_fits.append(public)
        fit_count += 1
        outer_ledgers.extend([_ledger(outer_query, outer_predictions, 'logistic_selected', chosen),
                              _ledger(outer_query, outer_reference, 'constant_reference', pd.NA)])
        folds.append({'outer_fold': fold, 'inner_training_support': inner_support,
                      'inner_reference': inner_reference_evaluation, 'inner_candidates': candidates,
                      'selection': selection, 'outer_selected': outer_evaluation,
                      'outer_reference': reference_evaluation})
        emit({'phase': 'outer_fit_complete', 'outer_fold': fold, 'selected_C': chosen,
              'completed_estimator_fits': fit_count, 'query_orders': len(outer_query)})
    if fit_count != 12 or len(private_fits) != 12 or tracker['completed_estimator_fits'] != 12:
        raise ValueError('Exactly twelve fresh estimator fits are required')
    tracker['phase'] = 'final_source_verification'
    verify_sources()
    inner_frame = pd.concat(inner_ledgers, ignore_index=True)
    outer_frame = pd.concat(outer_ledgers, ignore_index=True)
    expected_inner_rows = sum(item['inner_reference']['coverage']['full_orders'] for item in folds) * 4
    expected_outer_rows = sum(item['outer_selected']['coverage']['full_orders'] for item in folds) * 2
    if (len(inner_frame) != expected_inner_rows or len(outer_frame) != expected_outer_rows
            or len(inner_ledgers) + len(outer_ledgers) != 18):
        raise ValueError('Every full query requires all eighteen prediction blocks')
    public = {'outer_folds': folds, 'fit_context_audits': public_fits,
              'aggregate_selected': evaluation.macro_average_precision([fold['outer_selected'] for fold in folds]),
              'aggregate_reference': evaluation.macro_average_precision([fold['outer_reference'] for fold in folds]),
              'execution': {'estimator_fits_completed': fit_count, 'inner_candidates_evaluated': 9,
                            'outer_refits_completed': 3, 'reference_prior_computations': 6,
                            'prediction_blocks_completed': len(inner_ledgers) + len(outer_ledgers),
                            'score_rows_across_blocks': len(inner_frame) + len(outer_frame),
                            'all_queries_scored_including_unknown': True,
                            'unknown_fitted_or_used_in_metrics': False,
                            'outer_labels_used_in_selection': False, 'automatic_retries': 0}}
    return public, inner_frame, outer_frame, {
        'fit_records': private_fits, 'model_objects_persisted': False}


def execute_training(bundle, spec, progress=None, source_verifier=None):
    tracker = {'phase': 'execution_specification_validation', 'outer_fold': None, 'role': None,
               'C': None, 'completed_estimator_fits': 0}
    try:
        return _execute_training(bundle, spec, progress or (lambda payload: None), tracker,
                                  source_verifier or bundle.verify_stable)
    except Exception as cause:
        raise TrainingStopped(tracker, cause) from cause


def _csv_bytes(frame):
    return frame.to_csv(index=False, lineterminator='\n', date_format='%Y-%m-%d %H:%M:%S',
                        na_rep='', float_format='%.17g').encode('utf-8')


def read_score_csv(data):
    frame = pd.read_csv(io.BytesIO(data), dtype='string', keep_default_na=False, float_precision='round_trip')
    if list(frame.columns) != SCORE_COLUMNS:
        raise ValueError('Unexpected score ledger schema')
    for name in ('fit_at', 'prediction_time', 'window_deadline', 'observation_cutoff', 'first_visible_answer_at'):
        raw = frame[name]
        frame[name] = files.parse_clock(raw.replace('', pd.NA))
        if (raw.ne('') & frame[name].isna()).any():
            raise ValueError('Invalid ledger timestamp')
    for name in ('horizon_complete', 'role_label_usable'):
        if not frame[name].isin(['True', 'False']).all():
            raise ValueError('Invalid ledger boolean')
        frame[name] = frame[name].eq('True')
    if not frame.y.isin(['', '0', '1']).all():
        raise ValueError('Invalid nullable ledger labels')
    frame['y'] = pd.to_numeric(frame.y.replace('', pd.NA)).astype('Int64')
    frame['C'] = pd.to_numeric(frame.C.replace('', pd.NA)).astype('Float64')
    # Parsing as strings first preserves the decimal text, then Python's correctly
    # rounded float conversion reconstructs the original 17-digit binary64.
    frame['probability_low_1_2'] = frame.probability_low_1_2.map(float).astype('float64')
    for name in ('outer_fold', 'role', 'model', 'order_id', 'label_state'):
        frame[name] = frame[name].astype(object)
    return frame.loc[:, SCORE_COLUMNS]


def verify_score_bytes(frame, data):
    restored = read_score_csv(data)
    pd.testing.assert_frame_equal(frame.reset_index(drop=True), restored, check_dtype=False, check_exact=True)
    if not np.array_equal(frame.probability_low_1_2.to_numpy(), restored.probability_low_1_2.to_numpy()):
        raise ValueError('Probability binary64 values changed in CSV roundtrip')
    if restored.loc[~restored.role_label_usable, 'y'].notna().any():
        raise ValueError('Unknown score-ledger labels must remain nullable')
    return {'rows': len(frame), 'columns': len(SCORE_COLUMNS),
            'exact_cells_compared': len(frame) * len(SCORE_COLUMNS), 'binary64_probabilities_exact': True}


def ensure_outputs_absent(report_path, directory):
    paths = [Path(report_path)] + [Path(directory) / name for name in OUTPUT_NAMES + (FAILURE_NAME,)]
    if any(path.exists() for path in paths):
        raise ValueError('Final output already exists; refusing any additional training replay')


def preflight_execution_paths(bundle, spec, spec_path, guard_path, report_path, directory, root=ROOT):
    """Reject unsafe/control/input/output collisions before the first estimator fit."""
    root = Path(root).resolve()
    reject_output_aliases(report_path, root)
    reject_output_aliases(directory, root)
    report_path = files.safe_output(report_path, REPORT, root)
    directory = files.safe_output(directory, '', root, private=True)
    controls = {Path(spec_path).resolve(), Path(guard_path).resolve()}
    bound = merged_sources(spec['public_sources'], bundle.private_sources,
                           [files.descriptor(path, root) for path in controls])
    bound_paths = {(root / item['path']).resolve() for item in bound}
    candidates = [report_path] + [directory / name for name in OUTPUT_NAMES + (FAILURE_NAME,)]
    normalized = []
    for path in candidates:
        # Path.exists alone misses dangling symlinks; refuse aliases entirely.
        if path.is_symlink():
            raise ValueError('Final outputs cannot be symlink aliases')
        resolved = files.safe_output(path, REPORT if path == report_path else '', root,
                                     private=path != report_path)
        if resolved.exists() or resolved in bound_paths or resolved in controls:
            raise ValueError('Final output already exists or collides with a bound source')
        for ancestor in (resolved.parent, *resolved.parents):
            if ancestor.exists() and not ancestor.is_dir():
                raise ValueError('A final-output ancestor is not a directory')
            if ancestor == root:
                break
        normalized.append(resolved)
    if len(set(normalized)) != len(normalized):
        raise ValueError('Final output paths collide with each other')
    files.verify_sources(bound, root)
    return bound


def write_failure_receipt(error, directory, spec_path, root=ROOT):
    root = Path(root)
    path = files.safe_output(Path(directory) / FAILURE_NAME, '', root, private=True)
    context = error.context if isinstance(error, TrainingStopped) else {
        'phase': 'source_guard_or_publication', 'outer_fold': None, 'role': None, 'C': None,
        'completed_estimator_fits': 0}
    payload = {'status': 'stopped_no_fallback_no_partial_public_report',
               'execution_context': context, 'error_type': error.cause_type if isinstance(error, TrainingStopped) else type(error).__name__,
               'automatic_retry': False, 'specification_path': Path(spec_path).relative_to(root.resolve()).as_posix()}
    files.immutable_write(path, files.json_bytes(payload))
    return payload


def publish(bundle, spec, spec_path, guard_path, report_path, directory, execution, root=ROOT):
    root = Path(root)
    reject_output_aliases(report_path, root)
    reject_output_aliases(directory, root)
    spec_source, guard_source = verify_execution_specification(bundle, spec, spec_path, guard_path, root)
    report_path = files.safe_output(report_path, REPORT, root)
    directory = files.safe_output(directory, '', root, private=True)
    public, inner, outer, fit_audit = execution
    frames = {'inner_scores.csv': inner, 'outer_scores.csv': outer}
    payloads = {name: _csv_bytes(frame) for name, frame in frames.items()}
    checks = {name: verify_score_bytes(frame, payloads[name]) for name, frame in frames.items()}
    payloads['fit_audit.json'] = files.json_bytes(fit_audit)
    outputs = {name: {'path': (directory / name).relative_to(root.resolve()).as_posix(),
                      'rows': len(frame), 'columns': SCORE_COLUMNS} for name, frame in frames.items()}
    outputs.update({'fit_audit': {'path': (directory / 'fit_audit.json').relative_to(root.resolve()).as_posix(),
                                  'fit_records': 12},
                    'manifest': {'path': (directory / 'manifest.json').relative_to(root.resolve()).as_posix(),
                                 'private_digests_public': False}})
    result = {'format_version': 1, 'status': 'completed_real_offline_minimal_baseline',
              'specification': spec_source, 'method_reference': spec['method_reference'],
              'execution_plan': execution_plan(), 'sources': spec['public_sources'],
              'results': public, 'private_outputs': outputs,
              'source_roster_verification': bundle.summary,
              'verification': {'public_source_bindings': len(spec['public_sources']),
                               'private_source_bindings': len(bundle.private_sources),
                               'score_csv_exact_readback': checks,
                               'fit_eligible_rosters_and_scaler_samples_verified': 12,
                               'original_retained_test_scored': False, 'new_unseen_holdout_claim': False,
                               'dashboard': False},
              'limitations': ['Already inspected nested rolling development results, not a new unseen holdout.',
                              'Known-label metrics exclude unknown/nonresponse orders; full query scores are retained.',
                              'Raw event clocks are proxies; original ingestion, version and upstream completeness remain unverified.',
                              'Shared historical orders/customers across rolling folds prevent independent-fold interpretation.',
                              'Stage 4 remains pending data with unchanged daily 10% and five seeds.']}
    report_data = files.json_bytes(result)
    report_source = {'path': report_path.relative_to(root.resolve()).as_posix(), 'bytes': len(report_data),
                     'sha256': hashlib.sha256(report_data).hexdigest()}
    manifest = {'format_version': 1, 'specification': spec_source, 'input_guard': guard_source,
                'public_report': report_source,
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in payloads.items()},
                'completed_estimator_fits': 12, 'no_training_replay': True}
    payloads['manifest.json'] = files.json_bytes(manifest)
    bound = spec['public_sources'] + bundle.private_sources + [spec_source, guard_source]
    bound_paths = {(root / item['path']).resolve() for item in bound}
    output_paths = [files.safe_output(directory / name, '', root, private=True) for name in payloads]
    if report_path in output_paths or any(path in bound_paths for path in output_paths + [report_path]):
        raise ValueError('Final output collides with bound input or public report')
    for name, data in payloads.items():
        files.immutable_preflight(directory / name, data)
    files.immutable_preflight(report_path, report_data)
    bundle.verify_stable()
    files.verify_sources(bound, root)
    for name, data in payloads.items():
        files.immutable_write(directory / name, data)
    for name, frame in frames.items():
        verify_score_bytes(frame, (directory / name).read_bytes())
    if files.read_json(directory / 'fit_audit.json') != fit_audit or files.read_json(directory / 'manifest.json') != manifest:
        raise ValueError('Private JSON exact readback mismatch')
    bundle.verify_stable()
    files.verify_sources(bound, root)
    created_report = False
    try:
        # This run owns only an exclusive new file. A late verification failure
        # must not leave a completed public report beside a failure receipt.
        if report_path.exists():
            raise ValueError('Refusing to replace an existing completed report')
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open('xb') as stream:
            created_report = True
            stream.write(report_data)
        if files.read_json(report_path) != result:
            raise ValueError('Public report exact readback mismatch')
        files.verify_sources(bound, root)
        bundle.verify_stable()
    except Exception:
        if created_report and report_path.is_file() and report_path.read_bytes() == report_data:
            report_path.unlink()
        raise
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--specification', default=SPEC)
    parser.add_argument('--output', default=REPORT)
    parser.add_argument('--input-guard', default=GUARD)
    parser.add_argument('--private-directory', default=PRIVATE)
    args = parser.parse_args(argv)
    for path in (args.specification, args.input_guard, args.output, args.private_directory):
        reject_output_aliases(ROOT / path)
    spec_path = files.safe_output(ROOT / args.specification, SPEC)
    guard_path = files.safe_output(ROOT / args.input_guard, '', private=True)
    report_path = files.safe_output(ROOT / args.output, REPORT)
    directory = files.safe_output(ROOT / args.private_directory, '', private=True)
    if len({spec_path, guard_path, report_path}) != 3:
        raise ValueError('Specification, guard and report paths must be distinct')
    final_paths = {directory / name for name in OUTPUT_NAMES + (FAILURE_NAME,)}
    if spec_path in final_paths or guard_path in final_paths or report_path in final_paths:
        raise ValueError('Control path collides with a private final artifact')
    if not args.specification_only:
        ensure_outputs_absent(report_path, directory)
    if args.specification_only:
        bundle = load_sources()
        spec = freeze_specification(bundle, spec_path, guard_path)
        print(json.dumps({'phase': 'training_specification_frozen', 'public_source_bindings': len(spec['public_sources']),
                          'estimator_fits': 0}), flush=True)
        return
    completed = False
    try:
        bundle = load_sources()
        spec = files.read_json(spec_path)
        verify_execution_specification(bundle, spec, spec_path, guard_path)
        bound = preflight_execution_paths(bundle, spec, spec_path, guard_path, report_path, directory)
        execution = execute_training(bundle, spec, progress=lambda payload: print(json.dumps(payload), flush=True),
                                      source_verifier=lambda: files.verify_sources(bound))
        completed = True
        result = publish(bundle, spec, spec_path, guard_path, report_path, directory, execution)
    except Exception as error:
        if completed:
            error = TrainingStopped({'phase': 'publication', 'outer_fold': None, 'role': None,
                                     'C': None, 'completed_estimator_fits': 12}, error)
        receipt = write_failure_receipt(error, directory, spec_path)
        print(json.dumps({'phase': 'stopped', 'failure_receipt': str(directory / FAILURE_NAME),
                          'completed_estimator_fits': receipt['execution_context']['completed_estimator_fits']}), flush=True)
        raise
    print(json.dumps({'phase': result['status'], 'completed_estimator_fits': 12,
                      'outer_development_months': 3, 'new_unseen_holdout_claim': False}), flush=True)


if __name__ == '__main__':
    main()
