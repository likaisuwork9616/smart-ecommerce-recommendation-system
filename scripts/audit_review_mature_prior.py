"""Freeze and audit mature H60 priors with no scoring or parameter updates."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts import freeze_review_dataset as files
from scripts import review_baseline_sources as sources
from scripts import review_month_ablation_sources as model_guard
from scripts import review_mature_prior_audit as core

SPEC='reports/stage5/review_mature_prior_specification.json'
REPORT='reports/stage5/review_mature_prior_audit.json'
GUARD='.runtime/stage5_review_mature_prior_v1/input_guard.json'
PARENT_SPEC='reports/stage5/review_ablation_diagnostic_specification.json'
PARENT_REPORT='reports/stage5/review_ablation_diagnostics.json'
PARENT_VERIFICATION='reports/stage5/review_ablation_diagnostic_verification.json'
CODE=('scripts/audit_review_mature_prior.py','scripts/review_mature_prior_audit.py',
      'tests/test_review_mature_prior_audit.py','tests/test_audit_review_mature_prior.py')
PINS={PARENT_SPEC:'dc36819ae685ff631b93635c0cf83da9ada5d7dc77ff3e29bb018c6167344ea2',
      PARENT_REPORT:'7731b175ca0fa48695bc43435a30e975e023c29da2abac5190ff4f4764f007f5',
      PARENT_VERIFICATION:'d08a7fdf0b9d61a6a435330ecdb8f3478fb45c7464ea5c132da4d98def1abbd2'}


def load_snapshot(root=ROOT):
    root=Path(root).resolve()
    parents=[files.descriptor(root/n,root) for n in PINS]
    if any(v['sha256']!=PINS[v['path']] for v in parents):
        raise ValueError('Frozen paired diagnostic parent changed')
    prior_spec=files.read_json(root/PARENT_SPEC)
    prior_report=files.read_json(root/PARENT_REPORT)
    prior_verification=files.read_json(root/PARENT_VERIFICATION)
    parent_guard_path=prior_spec['private_source_guard']['path']
    parent_guard=files.read_json(root/parent_guard_path)
    parent_descriptor=files.descriptor(root/PARENT_SPEC,root)
    if (parent_guard['specification']!=parent_descriptor
            or prior_report['specification']!=parent_descriptor
            or prior_report['status']!='completed_read_only_paired_ablation_diagnostics'
            or prior_verification['status']!='passed_read_only_paired_diagnostic_verification'
            or parent_guard_path!='.runtime/stage5_review_ablation_diagnostics_v1/input_guard.json'
            or prior_spec['private_source_guard']['input_paths']!=[v['path'] for v in parent_guard['private_sources']]):
        raise ValueError('Paired diagnostic report or private guard is inconsistent')
    files.verify_sources(prior_spec['public_sources']+parent_guard['private_sources']+parents,root)
    bundle=sources.load_verified_sources(root)
    public=sources.merge_sources(bundle.public_sources,prior_spec['public_sources'],parents)
    private=sources.merge_sources(bundle.private_sources,parent_guard['private_sources'],
        [files.descriptor(root/parent_guard_path,root)])
    if {v['path'] for v in public}&{v['path'] for v in private}:
        raise ValueError('Public/private binding overlap')
    files.verify_sources(public+private,root)
    return bundle,public,private


def output(name,root):
    path=Path(root)/name
    # Reject link aliases before resolve; designated paths are versioned, not arbitrary.
    if any(p.is_symlink() for p in [path,*path.parents]):
        raise ValueError('Output aliases are forbidden')
    return files.safe_output(path,'' if name==GUARD else name,root,private=name==GUARD)


def make_specification(public,private,root=ROOT):
    bound=sources.merge_sources(public,[files.descriptor(Path(root)/n,root) for n in CODE])
    return {'format_version':1,'role':'read_only_mature_prior_temporal_drift_audit',
        'protocol':core.audit_protocol(),'public_sources':bound,
        'private_source_guard':{'path':GUARD,'input_paths':[d['path'] for d in private],'private_digests_public':False},
        'software_versions':sources.baseline.software_versions(),
        'output':REPORT,'new_training':False,'dashboard':False,
        'stage4':{'status':'pending_data','daily_budget':.1,'seeds':[11,29,42,73,101],'modified':False}}


def freeze(public,private,root):
    spec=make_specification(public,private,root);data=files.json_bytes(spec)
    descriptor={'path':SPEC,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    guard=files.json_bytes({'format_version':1,'specification':descriptor,'private_sources':private})
    targets=[(output(SPEC,root),data),(output(GUARD,root),guard)]
    for path,payload in targets:files.immutable_preflight(path,payload)
    files.verify_sources(spec['public_sources']+private,root)
    for path,payload in targets:files.immutable_write(path,payload)
    files.verify_sources(spec['public_sources']+private+[descriptor],root)
    return spec


def audit(bundle):
    folds=[];fit_times=set();rows=0
    for plan in files.calendar_split_plan():
        fold=plan['outer_fold'];roles={role:bundle.role_block(fold,role) for role in sources.ROLES}
        item={'outer_fold':fold,'contexts':[]}
        for train_role,query_role in [('inner_train_pool','inner_validation'),('outer_train_pool','outer_evaluation')]:
            train=roles[train_role];query=roles[query_role]
            # Historical prior is finalized before the query's retrospective summary.
            prior=core.training_prior(train)
            compared=core.compare_retrospective_query(prior,query)
            if set(train.order_id)&set(query.order_id):
                raise ValueError('Training and query rosters overlap')
            item['contexts'].append({'training_role':train_role,'query_role':query_role,
                'history_prior':prior,'retrospective_query_comparison':compared,
                'train_query_order_overlap':0})
            fit_times.add(prior['fit_at']);rows+=len(train)+len(query)
        item['shared_history_transition']=core.shared_history_transition(roles['inner_train_pool'],roles['outer_train_pool'])
        folds.append(item)
    if rows!=len(bundle.membership) or len(fit_times)!=5:
        raise ValueError('Expected complete12-role roster and five distinct fit times')
    return folds,rows


def run(root=ROOT,specification_only=False):
    root=Path(root).resolve()
    with model_guard.forbid_model_execution() as calls:
        bundle,public,private=load_snapshot(root)
        if specification_only:
            return freeze(public,private,root)
        spec=files.read_json(output(SPEC,root));source=files.descriptor(root/SPEC,root)
        guard=files.read_json(output(GUARD,root))
        if (spec!=make_specification(public,private,root)
                or guard!={'format_version':1,'specification':source,'private_sources':private}):
            raise ValueError('Frozen mature-prior policy, code or sources changed')
        bound=spec['public_sources']+private+[source,files.descriptor(root/GUARD,root)]
        files.verify_sources(bound,root)
        folds,rows=audit(bundle)
        bundle.verify_stable();files.verify_sources(bound,root)
        if calls['forbidden_calls']:
            raise RuntimeError('Forbidden execution prevents publication')
        result={'format_version':1,'status':'completed_read_only_mature_prior_temporal_audit',
            'specification':source,'protocol':spec['protocol'],'sources':spec['public_sources'],
            'folds':folds,'verification':{'public_bindings':len(spec['public_sources']),
                'private_bindings':len(private),'full_role_blocks':12,'membership_rows':rows,
                'fit_contexts':6,'distinct_fit_times':5,'query_labels_used_for_prior':0,
                'global_labels_joined_into_fits':False,'score_values_read':False,'model_parameters_read':False,
                'forbidden_model_calls':calls['forbidden_calls'],'feature_builds':0,'new_fits':0,
                'transforms':0,'predictions':0,'performance_metrics':0,'parameter_updates':0,
                'source_bytes_checked_before_after':True},
            'stage4':spec['stage4'],'dashboard':False,
            'limitations':['Retrospective known-query rates are descriptions, never fit inputs or window-selection criteria.',
                'Known mature responders are a conditional target; mature unknown and immature orders remain nullable.',
                'Historical ingestion/version availability remains an unverified event-proxy assumption.',
                'Rolling roles and recent windows reuse orders and cannot be treated as independent samples.',
                'No model/threshold/calibration/performance or causal conclusion follows from descriptive prior gaps.']}
        data=files.json_bytes(result);path=output(REPORT,root)
        files.immutable_preflight(path,data);existed=path.exists()
        try:
            files.immutable_write(path,data)
            if path.read_bytes()!=data:raise ValueError('Published audit readback differs')
            files.verify_sources(bound,root);bundle.verify_stable()
        except Exception:
            if not existed and path.is_file() and path.read_bytes()==data:path.unlink()
            raise
        return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--specification-only',action='store_true')
    args=p.parse_args(argv);result=run(specification_only=args.specification_only)
    print(result.get('status','frozen_read_only_mature_prior_specification'))


if __name__=='__main__':main()
