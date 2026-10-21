"""Bounded diagnostics of existing Stage 5 scores; model execution is forbidden."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

try:
    from scripts import freeze_review_dataset as files
    from scripts import review_baseline_evaluation as evaluation
    from scripts import review_baseline_sources as sources
    from scripts import run_review_baseline as training
    from scripts import review_score_diagnostics as core
except ModuleNotFoundError:
    import freeze_review_dataset as files
    import review_baseline_evaluation as evaluation
    import review_baseline_sources as sources
    import run_review_baseline as training
    import review_score_diagnostics as core

ROOT = Path(__file__).resolve().parents[1]
SPEC = 'reports/stage5/review_score_diagnostic_specification.json'
REPORT = 'reports/stage5/review_score_diagnostics.json'
PRIVATE = '.runtime/stage5_review_score_diagnostics_v1'
GUARD = PRIVATE + '/input_guard.json'
RECEIPT = '.runtime/stage5_offline_formal_execution_proof.json'
CODE = ('scripts/diagnose_review_scores.py', 'scripts/review_score_diagnostics.py',
        'tests/test_review_score_diagnostic_runner.py', 'tests/test_review_score_diagnostics.py')
PARENTS = {
    training.SPEC: 'f9ddfd7c729b293b16cdb9202170765103df2a216a191438103b7349c92c285d',
    training.REPORT: '4bb7c8844872d81f58bfd85d32f087c0745e467997d394a46414e3e4fa7b0c0b',
}


@contextmanager
def forbid_model_execution():
    """Fail before any model/pipeline construction, fit, transform or prediction."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    counters = {'forbidden_calls': 0}

    def forbidden(*args, **kwargs):
        counters['forbidden_calls'] += 1
        raise RuntimeError('Read-only diagnostics forbid model execution')

    with ExitStack() as stack:
        targets = [(training.GuardedReviewBaseline, ('__init__', 'fit_orders', 'transform_orders', 'predict_orders')),
                   (LogisticRegression, ('fit', 'predict', 'predict_proba')),
                   (StandardScaler, ('fit', 'partial_fit', 'transform')),
                   (OneHotEncoder, ('fit', 'transform'))]
        for cls, methods in targets:
            for method in methods:
                stack.enter_context(patch.object(cls, method, forbidden))
        yield counters


def _digest(item):
    return {key: item[key] for key in ('bytes', 'sha256')}


def verify_training_snapshot(bundle, root=ROOT):
    """Bind the existing local receipt chain to immutable public parents."""
    root = Path(root)
    parents = [files.descriptor(root / path, root) for path in PARENTS]
    if any(item['sha256'] != PARENTS[item['path']] for item in parents):
        raise ValueError('Original training specification or report changed')
    spec, report = (files.read_json(root / path) for path in (training.SPEC, training.REPORT))
    spec_source, guard_source = training.verify_execution_specification(
        bundle, spec, root / training.SPEC, root / training.GUARD, root)
    if (report['status'] != 'completed_real_offline_minimal_baseline'
            or report['specification'] != spec_source or report['sources'] != spec['public_sources']):
        raise ValueError('Training report and source specification disagree')
    directory = root / training.PRIVATE
    if (directory / training.FAILURE_NAME).exists():
        raise ValueError('Original training has a failure receipt')
    manifest_source = files.descriptor(directory / 'manifest.json', root)
    manifest = files.read_json(directory / 'manifest.json')
    receipt_source = files.descriptor(root / RECEIPT, root)
    receipt = files.read_json(root / RECEIPT)
    report_source = files.descriptor(root / training.REPORT, root)
    if (receipt['status'] != 'passed_one_formal_training_run'
            or receipt['real_classifier_fits'] != 12 or receipt['additional_training_replays'] != 0
            or receipt['public_specification'] != _digest(spec_source)
            or receipt['public_report'] != _digest(report_source)
            or receipt['private_manifest'] != _digest(manifest_source)):
        raise ValueError('Original local formal receipt is inconsistent')
    if (manifest['format_version'] != 1 or manifest['specification'] != spec_source
            or manifest['public_report'] != report_source or manifest['input_guard'] != guard_source
            or manifest['completed_estimator_fits'] != 12 or manifest['no_training_replay'] is not True
            or set(manifest['files']) != {'inner_scores.csv', 'outer_scores.csv', 'fit_audit.json'}):
        raise ValueError('Original frozen output manifest is inconsistent')
    output_sources = []
    for name, expected in manifest['files'].items():
        actual = files.descriptor(directory / name, root)
        if _digest(actual) != expected:
            raise ValueError('Frozen training output changed: ' + name)
        output_sources.append(actual)
    public = sources.merge_sources(spec['public_sources'], parents)
    private = sources.merge_sources(bundle.private_sources,
                                    [guard_source, manifest_source, receipt_source], output_sources)
    files.verify_sources(public + private, root)
    return report, public, private


def make_specification(public, private, root=ROOT):
    bound = sources.merge_sources(public, [files.descriptor(Path(root) / path, root) for path in CODE])
    return {'format_version': 1, 'role': 'read_only_existing_development_score_diagnostics',
            'protocol': core.diagnostic_protocol(), 'public_sources': bound,
            'training_references': [item for item in bound if item['path'] in PARENTS],
            'private_source_guard': {'path': GUARD, 'input_paths': [item['path'] for item in private],
                                     'private_digests_public': False},
            'output': REPORT, 'no_fit_transform_predict_or_score_replay': True,
            'scope': 'existing_local_snapshot_not_original_operational_ingestion_proof',
            'stage4': 'pending_data_daily_10_percent_seeds_11_29_42_73_101_unchanged',
            'dashboard': False}


def _outputs(root):
    result = []
    for name, private in ((SPEC, False), (GUARD, True), (REPORT, False)):
        path = Path(root) / name
        training.reject_output_aliases(path, root)
        result.append(files.safe_output(path, '' if private else name, root, private=private))
    return result


def freeze_specification(public, private, root=ROOT):
    spec_path, guard_path, _ = _outputs(root)
    spec = make_specification(public, private, root)
    data = files.json_bytes(spec)
    descriptor = {'path': SPEC, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    guard = {'format_version': 1, 'specification': descriptor, 'private_sources': private,
             'scope': 'existing_local_receipt_snapshot_not_independent_ingestion_evidence'}
    guard_data = files.json_bytes(guard)
    files.immutable_preflight(spec_path, data)
    files.immutable_preflight(guard_path, guard_data)
    files.verify_sources(spec['public_sources'] + private, root)
    files.immutable_write(spec_path, data)
    files.immutable_write(guard_path, guard_data)
    files.verify_sources(spec['public_sources'] + private + [descriptor], root)
    return spec


def verify_diagnostic_specification(public, private, root=ROOT):
    spec_path, guard_path, _ = _outputs(root)
    spec = files.read_json(spec_path)
    if spec != make_specification(public, private, root):
        raise ValueError('Frozen diagnostic plan, code or public sources changed')
    spec_source, guard_source = files.descriptor(spec_path, root), files.descriptor(guard_path, root)
    guard = files.read_json(guard_path)
    if guard['specification'] != spec_source or guard['private_sources'] != private:
        raise ValueError('Frozen diagnostic private inputs changed')
    bound = spec['public_sources'] + private + [spec_source, guard_source]
    files.verify_sources(bound, root)
    return spec, spec_source, bound


def assert_same(actual, expected):
    """Compare existing metric aggregates without choosing models or thresholds."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise ValueError('Frozen aggregate keys mismatch')
        for key in expected:
            assert_same(actual[key], expected[key])
    elif isinstance(expected, float):
        if (not isinstance(actual, (float, int)) or not np.isfinite(actual)
                or not np.isclose(actual, expected, atol=1e-12, rtol=0)):
            raise ValueError('Frozen aggregate numeric mismatch')
    elif actual != expected:
        raise ValueError('Frozen aggregate mismatch')


def verify_score_block(frame, truth, model, C, expected, prior=None):
    if list(frame.columns) != training.SCORE_COLUMNS or len(frame) != len(truth):
        raise ValueError('Frozen score schema or complete role size mismatch')
    if frame.empty or not frame.model.eq(model).all():
        raise ValueError('Frozen score model mismatch')
    if not (frame.C.isna().all() if C is None else frame.C.notna().all() and frame.C.eq(C).all()):
        raise ValueError('Frozen selected/candidate C mismatch')
    try:
        pd.testing.assert_frame_equal(frame[files.MEMBERSHIP_COLUMNS].reset_index(drop=True),
                                      truth[files.MEMBERSHIP_COLUMNS].reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError('Frozen score metadata or canonical roster mismatch') from exc
    p = pd.Series(frame.probability_low_1_2.to_numpy(dtype=float), index=truth.order_id)
    actual = evaluation.evaluate_role(p, truth)
    if prior is not None and not np.equal(p.to_numpy(), prior).all():
        raise ValueError('Reference probability differs from eligible fit prevalence')
    assert_same(actual, expected)
    return p


def load_verified_score_blocks(bundle, old_report, root=ROOT):
    result, row_count = {}, 0
    for filename, role, train_role in (
            ('inner_scores.csv', 'inner_validation', 'inner_train_pool'),
            ('outer_scores.csv', 'outer_evaluation', 'outer_train_pool')):
        ledger = training.read_score_csv((Path(root) / training.PRIVATE / filename).read_bytes())
        consumed = pd.Series(False, index=ledger.index)
        for old in old_report['results']['outer_folds']:
            fold = old['outer_fold']
            truth = bundle.role_block(fold, role)
            prior = evaluation.constant_reference_probability(bundle.role_block(fold, train_role))
            inner = role == 'inner_validation'
            plans = [('constant_reference', None, old['inner_reference' if inner else 'outer_reference'])]
            plans += ([('logistic_candidate', item['C'], item['evaluation']) for item in old['inner_candidates']]
                      if inner else [('logistic_selected', old['selection']['selected_C'], old['outer_selected'])])
            for model, C, expected in plans:
                mask = ledger.outer_fold.eq(fold) & ledger.role.eq(role) & ledger.model.eq(model)
                mask &= ledger.C.isna() if C is None else ledger.C.eq(C).fillna(False)
                if (consumed & mask).any():
                    raise ValueError('Duplicate frozen score block')
                p = verify_score_block(ledger.loc[mask], truth, model, C, expected,
                                       prior if model == 'constant_reference' else None)
                result[(fold, role, model, C)] = p
                consumed |= mask
        if not consumed.all():
            raise ValueError('Unexpected frozen ledger rows or blocks')
        row_count += len(ledger)
    if len(result) != 18 or row_count != old_report['results']['execution']['score_rows_across_blocks']:
        raise ValueError('Frozen 18-block score coverage mismatch')
    return result, row_count


def diagnose(bundle, old_report, blocks):
    folds = []
    raw = bundle.raw_orders
    for old in old_report['results']['outer_folds']:
        fold = old['outer_fold']
        roles = {role: bundle.role_block(fold, role) for role in sources.ROLES}
        item = {'outer_fold': fold, 'roles': {name: core.role_summary(block) for name, block in roles.items()},
                'selected_C_unchanged': old['selection']['selected_C'], 'queries': {}}
        for role, train_role in (('inner_validation', 'inner_train_pool'),
                                 ('outer_evaluation', 'outer_train_pool')):
            truth, train = roles[role], roles[train_role]
            eligible = train.loc[train.role_label_usable, 'order_id']
            train_x = core.derive_clock_features(raw, eligible)
            query_x = core.derive_clock_features(raw, truth.order_id)
            scores = [{'model': model, 'C': C, 'profile': core.score_profile(p, truth)}
                      for (f, r, model, C), p in blocks.items() if f == fold and r == role]
            query = {'training_role': train_role,
                     'feature_support': core.compare_feature_support(train_x, query_x, truth),
                     'scores': scores}
            if role == 'outer_evaluation':
                query['paired_existing_loss'] = core.paired_loss_profile(
                    blocks[(fold, role, 'logistic_selected', old['selection']['selected_C'])],
                    blocks[(fold, role, 'constant_reference', None)], truth)
            item['queries'][role] = query
        folds.append(item)
    return folds


def run(root=ROOT, specification_only=False):
    root = Path(root).resolve()
    with forbid_model_execution() as calls:
        bundle = sources.load_verified_sources(root)
        old_report, public, private = verify_training_snapshot(bundle, root)
        if specification_only:
            result = freeze_specification(public, private, root)
            bundle.verify_stable()
            return result
        spec, spec_source, bound = verify_diagnostic_specification(public, private, root)
        blocks, rows = load_verified_score_blocks(bundle, old_report, root)
        folds = diagnose(bundle, old_report, blocks)
        bundle.verify_stable()
        files.verify_sources(bound, root)
        if calls['forbidden_calls']:
            raise RuntimeError('Forbidden model execution was attempted')
        result = {'format_version': 1, 'status': 'completed_read_only_frozen_score_diagnostics',
                  'specification': spec_source, 'protocol': spec['protocol'],
                  'sources': spec['public_sources'], 'folds': folds,
                  'verification': {'public_bindings': len(spec['public_sources']),
                                   'private_bindings': len(private), 'score_blocks_verified': len(blocks),
                                   'score_rows_verified': rows, 'existing_metrics_match_atol': 1e-12,
                                   'exact_role_metadata_verified': True, 'all_unknown_scores_retained': True,
                                   'source_bytes_checked_before_after': True,
                                   'model_fit_calls': 0, 'model_transform_calls': 0, 'model_predict_calls': 0,
                                   'forbidden_model_calls': calls['forbidden_calls'],
                                   'fit_audit_read_as_model_parameters': False},
                  'limitations': ['Previously inspected development months; no new holdout or performance claim.',
                                  'Known-label rates exclude unknown and nonresponse orders.',
                                  'Fixed one-dimensional descriptions cannot establish causes or a beneficial intervention.',
                                  'Local receipt integrity does not prove original ingestion/version availability.',
                                  'Rolling roles reuse orders; candidate rows are not independent observations.',
                                  'Stage 4 pending data; daily 10% and five seeds unchanged; no Dashboard.']}
        path = _outputs(root)[2]
        data = files.json_bytes(result)
        files.immutable_preflight(path, data)
        existed = path.exists()
        try:
            files.immutable_write(path, data)
            if path.read_bytes() != data:
                raise ValueError('Diagnostic aggregate readback mismatch')
            files.verify_sources(bound, root)
            bundle.verify_stable()
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
    print(result.get('status', 'frozen_read_only_diagnostic_specification'))


if __name__ == '__main__':
    main()
