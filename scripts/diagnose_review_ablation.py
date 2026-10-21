"""Describe both frozen Stage 5 score arms without any model execution."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import freeze_review_dataset as files
from scripts import review_baseline_sources as common
from scripts import review_month_ablation_sources as sources
from scripts import review_month_ablation_pairing as pairing
from scripts import diagnose_review_scores as old_diagnostic
from scripts import review_ablation_diagnostics as core
from scripts import run_review_baseline as codec

SPEC = 'reports/stage5/review_ablation_diagnostic_specification.json'
REPORT = 'reports/stage5/review_ablation_diagnostics.json'
GUARD = '.runtime/stage5_review_ablation_diagnostics_v1/input_guard.json'
TREATMENT = 'reports/stage5/review_month_ablation_training.json'
ACCEPTANCE = 'reports/stage5/review_month_ablation_training_acceptance.json'
PRIVATE = '.runtime/stage5_review_month_ablation_training_v1'
DISPATCH = 'reports/stage5/review_month_ablation_dispatcher_specification.json'
INPUT_GUARD = '.runtime/stage5_review_month_ablation_dispatcher_v1/input_guard.json'
PROOF = '.runtime/stage5_real_ablation_execution_proof.json'
CODE = ('scripts/diagnose_review_ablation.py', 'scripts/review_ablation_diagnostics.py',
        'tests/test_review_ablation_diagnostics.py', 'tests/test_diagnose_review_ablation.py',
        'scripts/diagnose_review_scores.py', 'scripts/review_score_diagnostics.py')
PARENTS = {
    TREATMENT: '11ab4764226e40e56c1a9b0785ebb517fc661172cac146c50c0d43e38486c040',
    ACCEPTANCE: '2e80912cdbd4057ebee7a0355fa922b6ed52a40a9315d711411b4c4d06e154c6',
    codec.REPORT: '4bb7c8844872d81f58bfd85d32f087c0745e467997d394a46414e3e4fa7b0c0b',
}


@contextmanager
def forbid_model_execution():
    """Guard both builders, pipelines, sklearn methods and candidate selection."""
    from scripts import review_baseline_evaluation as evaluation
    from sklearn.linear_model import LogisticRegression
    with old_diagnostic.forbid_model_execution() as attempts:
        def forbidden(*args, **kwargs):
            attempts['forbidden_calls'] += 1
            raise RuntimeError('Paired diagnostics forbid model execution and candidate selection')
        with ExitStack() as stack:
            for module in (sources.control_pipeline, sources.treatment_pipeline):
                stack.enter_context(patch.object(module, 'build_primary_features', forbidden))
            for method in ('__init__','fit_orders','transform_orders','predict_orders'):
                stack.enter_context(patch.object(sources.treatment_pipeline.GuardedReviewMonthAblation, method, forbidden))
            stack.enter_context(patch.object(LogisticRegression, '__init__', forbidden))
            stack.enter_context(patch.object(evaluation, 'select_candidate', forbidden))
            yield attempts
            if attempts['forbidden_calls']:
                raise RuntimeError('Forbidden execution was attempted')


def verify_snapshot(bundle, root=ROOT):
    """Validate completed versions; never call empty-output training preflight."""
    root = Path(root)
    parents = [files.descriptor(root / n, root) for n in PARENTS]
    if any(d['sha256'] != PARENTS[d['path']] for d in parents):
        raise ValueError('Frozen completed training or acceptance report changed')
    report = files.read_json(root / TREATMENT)
    accepted = files.read_json(root / ACCEPTANCE)
    if (report['status'] != 'completed_real_offline_month_ablation'
            or accepted['status'] != 'passed_real_offline_month_ablation_delivery_acceptance'):
        raise ValueError('Completed frozen treatment and accepted delivery required')
    expected_names = {'inner_scores.csv', 'outer_scores.csv', 'fit_audit.json',
                      'paired_acceptance.json', 'manifest.json'}
    directory = root / PRIVATE
    if (not directory.is_dir() or {p.name for p in directory.iterdir()} != expected_names
            or any(p.is_symlink() or not p.is_file() for p in directory.iterdir())):
        raise ValueError('Treatment namespace must contain exactly five successful files')
    manifest = files.read_json(directory / 'manifest.json')
    dispatch = files.read_json(root / DISPATCH)
    guard = files.read_json(root / INPUT_GUARD)
    dispatch_source, guard_source = (files.descriptor(root / n, root) for n in (DISPATCH, INPUT_GUARD))
    references = {
        'execution_specification': dispatch['execution_specification'],
        'training_dispatcher_binding': dispatch_source,
        'input_guard': guard_source,
        'control_manifest': files.descriptor(root / codec.PRIVATE / 'manifest.json', root),
    }
    if (guard['specification'] != dispatch_source or manifest['completed_estimator_fits'] != 12
            or manifest['no_training_replay'] is not True or manifest['public_report'] != parents[0]
            or set(manifest['files']) != expected_names - {'manifest.json'}):
        raise ValueError('Treatment manifest or dispatcher guard differs')
    for key, value in references.items():
        if manifest[key] != value:
            raise ValueError('Completed treatment reference differs: ' + key)
    if (report['execution_specification'] != references['execution_specification']
            or report['training_dispatcher_binding'] != dispatch_source):
        raise ValueError('Report does not bind completed execution')
    payloads = [files.descriptor(directory / n, root) for n in sorted(expected_names)]
    for name, d in manifest['files'].items():
        if d != files.descriptor(directory / name, root):
            raise ValueError('Treatment payload bytes changed: ' + name)
    pair = files.read_json(directory / 'paired_acceptance.json')
    for key, value in references.items():
        if pair[key] != value:
            raise ValueError('Paired receipt reference differs')
    if manifest['paired_acceptance'] != manifest['files']['paired_acceptance.json']:
        raise ValueError('Paired receipt descriptor differs')
    for name, value in pair['treatment_file_digests'].items():
        if value != manifest['files'][name]:
            raise ValueError('Accepted treatment file differs')
    evidence = pair['acceptance']
    if (evidence['status'] != 'passed_complete_same_ID_treatment_control_pairing'
            or evidence['score_blocks'] != 18 or evidence['score_rows_per_arm'] != 108744):
        raise ValueError('Original full pairing acceptance required')
    data = files.json_bytes(report['results'])
    if evidence['accepted_public_results_digest'] != {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
        raise ValueError('Accepted public results changed')
    for name, d in evidence['accepted_treatment_file_digests'].items():
        if d != {k: manifest['files'][name][k] for k in ('bytes', 'sha256')}:
            raise ValueError('Accepted score or fit-audit digest changed')
    proof = files.read_json(root / PROOF)
    if (proof['status'] != 'passed' or proof['invocations'] != 1 or proof['automatic_retries'] != 0
            or proof['actual_estimator_fits_completed'] != 12 or proof['result'] != parents[0]):
        raise ValueError('Original one-run execution proof differs')
    public = common.merge_sources(bundle.public_sources, dispatch['public_sources'], parents,
        [dispatch_source, *references.values()])
    # Private reference descriptors stay in the guard, never in public_sources.
    private_paths = {INPUT_GUARD, references['control_manifest']['path']}
    public_private_refs = [d for d in public if d['path'] in private_paths]
    public = [d for d in public if d['path'] not in private_paths]
    private = common.merge_sources(bundle.private_sources, guard['private_sources'], public_private_refs,
        payloads, [files.descriptor(root / PROOF, root)])
    if {d['path'] for d in public} & {d['path'] for d in private}:
        raise ValueError('Public and private source overlap')
    files.verify_sources(public + private, root)
    return report, public, private


def output(name, root):
    codec.reject_output_aliases(Path(root) / name, root)
    return files.safe_output(Path(root) / name, name if name != GUARD else '', root, private=name == GUARD)


def make_specification(public, private, root=ROOT):
    bound = common.merge_sources(public, [files.descriptor(Path(root) / n, root) for n in CODE])
    return {'format_version': 1, 'role': 'read_only_paired_frozen_score_diagnostics',
            'protocol': core.diagnostic_protocol(), 'public_sources': bound,
            'private_source_guard': {'path': GUARD, 'input_paths': [d['path'] for d in private],
                                     'private_digests_public': False},
            'software_versions': sources.method.baseline.software_versions(),
            'output': REPORT, 'new_training': False, 'dashboard': False,
            'stage4': {'status': 'pending_data', 'daily_budget': .1, 'seeds': [11,29,42,73,101], 'modified': False}}


def freeze(public, private, root):
    spec = make_specification(public, private, root)
    data = files.json_bytes(spec)
    d = {'path': SPEC, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    guard = files.json_bytes({'format_version': 1, 'specification': d, 'private_sources': private})
    targets = [(output(SPEC, root), data), (output(GUARD, root), guard)]
    for p, b in targets:
        files.immutable_preflight(p, b)
    files.verify_sources(spec['public_sources'] + private, root)
    for p, b in targets:
        files.immutable_write(p, b)
    files.verify_sources(spec['public_sources'] + private + [d], root)
    return spec


def load_blocks(bundle, report, namespace, root):
    blocks = {}; rows = 0
    for name, role in [('inner_scores.csv','inner_validation'), ('outer_scores.csv','outer_evaluation')]:
        ledger = codec.read_score_csv((Path(root) / namespace / name).read_bytes())
        consumed = set()
        for fold in pairing._report_folds(report):
            f = fold['outer_fold']; truth = bundle.role_block(f, role)
            prior = pairing._prior(bundle, f, role)
            for model, C in pairing._plans(role, fold['selection']['selected_C']):
                frame = ledger.loc[pairing._select(ledger, f, role, model, C)]
                pairing.validate_score_block(frame, truth, model, C,
                                              prior=prior if model == 'constant_reference' else None)
                expected = (fold['inner_reference' if role == 'inner_validation' else 'outer_reference']
                            if model == 'constant_reference' else fold['outer_selected']
                            if model == 'logistic_selected' else next(
                                x['evaluation'] for x in fold['inner_candidates'] if x['C'] == C))
                p = old_diagnostic.verify_score_block(frame, truth, model, C, expected,
                    prior if model == 'constant_reference' else None)
                if consumed.intersection(frame.index):
                    raise ValueError('Overlapping frozen score blocks')
                consumed.update(frame.index); blocks[(f,role,model,C)] = p
        if consumed != set(ledger.index):
            raise ValueError('Unexpected frozen ledger rows')
        rows += len(ledger)
    if len(blocks) != 18 or rows != 108744:
        raise ValueError('Full frozen ledger coverage differs')
    return blocks


def diagnose(bundle, report, treatment, control):
    folds=[]; raw=bundle.raw_orders
    for t_fold, c_fold in zip(report['results']['outer_folds'], bundle.control_report['results']['outer_folds']):
        f=t_fold['outer_fold']
        if f != c_fold['outer_fold']:
            raise ValueError('Fold order mismatch')
        item={'outer_fold': f, 'frozen_treatment_C':t_fold['selection']['selected_C'],
              'frozen_control_C':c_fold['selection']['selected_C'], 'queries':{}}
        for role, train_role in [('inner_validation','inner_train_pool'),('outer_evaluation','outer_train_pool')]:
            truth=bundle.role_block(f,role); train=bundle.role_block(f,train_role)
            tx=core.descriptive.derive_clock_features(raw,train.loc[train.role_label_usable,'order_id'])
            qx=core.descriptive.derive_clock_features(raw,truth.order_id)
            query={'training_role':train_role,'support':core.feature_support(tx,qx,truth),'paired_scores':[]}
            for model,tc in pairing._plans(role,t_fold['selection']['selected_C']):
                cc=c_fold['selection']['selected_C'] if model=='logistic_selected' else tc
                c=control[(f,role,model,cc)];t=treatment[(f,role,model,tc)]
                if model=='constant_reference' and not c.equals(t):
                    raise ValueError('Frozen constant scores differ')
                query['paired_scores'].append({'model':model,'treatment_C':tc,'control_C':cc,
                    'profile':core.paired_profile(c,t,truth,include_ranking=model!='constant_reference')})
                if model=='logistic_selected':
                    query['feature_strata']=core.feature_strata(tx,qx,truth,c,t)
                    for by_feature in query['feature_strata'].values():
                        for metric,value in by_feature['summed_loss_delta_contributions'].items():
                            old_diagnostic.assert_same(value,t_fold['outer_selected']['metrics'][metric]-c_fold['outer_selected']['metrics'][metric])
            item['queries'][role]=query
        folds.append(item)
    return folds


def run(root=ROOT, specification_only=False):
    root=Path(root).resolve()
    with forbid_model_execution() as calls:
        bundle=sources.load_prepared_sources(root)
        report, public, private=verify_snapshot(bundle,root)
        if specification_only:
            return freeze(public,private,root)
        spec=files.read_json(output(SPEC,root))
        guard=files.read_json(output(GUARD,root))
        spec_source=files.descriptor(root/SPEC,root)
        if (spec != make_specification(public,private,root)
                or guard != {'format_version':1,'specification':spec_source,'private_sources':private}):
            raise ValueError('Frozen diagnostic code, protocol or inputs changed')
        bound=spec['public_sources']+private+[spec_source,files.descriptor(root/GUARD,root)]
        files.verify_sources(bound,root)
        treatment=load_blocks(bundle,report,PRIVATE,root)
        control=load_blocks(bundle,bundle.control_report,codec.PRIVATE,root)
        folds=diagnose(bundle,report,treatment,control)
        files.verify_sources(bound,root);bundle.verify_stable()
        result={'format_version':1,'status':'completed_read_only_paired_ablation_diagnostics',
                'specification':spec_source,'protocol':spec['protocol'],'sources':spec['public_sources'],
                'folds':folds,'verification':{'public_bindings':len(spec['public_sources']),
                    'private_bindings':len(private),'paired_score_blocks':18,'ranking_pairs':12,
                    'score_rows_per_arm':108744,'metadata_cells_both_arms':2609856,
                    'all_unknown_scores_retained':True,'known_only_metrics_match_original_atol':1e-12,
                    'fit_audit_hash_only_no_parameter_read':True,'source_bytes_checked_before_after':True,
                    'forbidden_model_calls':calls['forbidden_calls'],'new_fits':0,'transforms':0,
                    'new_predictions':0,'candidate_selections':0},
                'stage4':spec['stage4'],'dashboard':False,
                'limitations':['Descriptive analysis of already inspected development scores, not new performance or holdout evidence.',
                    'Outer arms independently selected C; outer differences do not hold C fixed.',
                    'Unknown labels retained in full rankings, excluded from loss denominators.',
                    'Strata are marginal descriptions, overlap across features and cannot be added across features.',
                    'No causal inference, significance tests, alert selection or threshold optimization.',
                    'Snapshot integrity does not establish original ingestion/version or upstream completeness.']}
        if calls['forbidden_calls']:
            raise RuntimeError('Forbidden model call prevents publication')
        data=files.json_bytes(result);path=output(REPORT,root)
        files.immutable_preflight(path,data);existed=path.exists()
        try:
            files.immutable_write(path,data)
            if path.read_bytes()!=data:
                raise ValueError('Published diagnostic bytes differ')
            files.verify_sources(bound,root);bundle.verify_stable()
        except Exception:
            if not existed and path.is_file() and path.read_bytes()==data:
                path.unlink()
            raise
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only',action='store_true')
    args=parser.parse_args(argv)
    result=run(specification_only=args.specification_only)
    print(result.get('status','frozen_read_only_paired_diagnostic_specification'))


if __name__=='__main__':
    main()
