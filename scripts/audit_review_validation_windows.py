"""Inventory calendar use and freeze conditional validation purposes; no targets."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import csv
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import freeze_review_dataset as files
from scripts import review_baseline_sources as sources
from scripts import review_month_ablation_sources as model_guard
from scripts import review_validation_windows as core

SPEC='reports/stage5/review_validation_window_specification.json'
REPORT='reports/stage5/review_validation_window_inventory.json'
PRIVATE='.runtime/stage5_review_validation_windows_v1'
GUARD=PRIVATE+'/input_guard.json'
HISTORY=PRIVATE+'/usage_history.json'
PARENT_SPEC='reports/stage5/review_mature_prior_specification.json'
PARENT_REPORT='reports/stage5/review_mature_prior_audit.json'
PARENT_VERIFY='reports/stage5/review_mature_prior_verification.json'
PINS={PARENT_SPEC:'02b8841d2b6b631e103950e5b9efcd8320ccf1796f5021b020611271bb7ddbf4',
      PARENT_REPORT:'ac30aef6cb036a13332119c45525c6d4290423fc71776c224cbe07b45dd9e674',
      PARENT_VERIFY:'7f0507ad829700e248875af650b18135ffc4b806bc7ee27cf458cd93d5d9dc13'}
CODE=('scripts/audit_review_validation_windows.py','scripts/review_validation_windows.py',
      'tests/test_review_validation_windows.py','tests/test_audit_review_validation_windows.py')
EVIDENCE=('scripts/audit_review_prediction_feasibility.py','scripts/freeze_review_dataset.py',
 'reports/stage5/review_dataset_specification.json','reports/stage5/review_dataset_audit.json',
 'reports/stage5/review_baseline_training.json','reports/stage5/review_month_ablation_training.json',
 'reports/stage5/review_ablation_diagnostics.json','reports/stage5/review_mature_prior_audit.json',
 'notebooks/03_olist_business_analysis.ipynb','sql/03_business_analysis.sql',
 'docs/STAGE3_BUSINESS_ANALYSIS.md','reports/images/olist_review_score_distribution.png',
 'reports/stage4/monthly_error_diagnostics.json','reports/stage4/event_source_availability.json')
SOURCE_METADATA='.runtime/event_source_public/public_source_findings.json'


@contextmanager
def forbid_execution():
    with model_guard.forbid_model_execution() as calls:
        def forbidden(*args,**kwargs):
            calls['forbidden_calls']+=1
            raise RuntimeError('Window inventory forbids target construction')
        with ExitStack() as stack:
            for n in ['label_asof','prepare_reviews','build_membership','write_private_bundle']:
                stack.enter_context(patch.object(files,n,forbidden))
            yield calls
            if calls['forbidden_calls']:raise RuntimeError('Forbidden execution was attempted')


def output(name,root):
    path=Path(root)/name
    if any(p.is_symlink() for p in [path,*path.parents]):raise ValueError('Output aliases forbidden')
    return files.safe_output(path,'' if name in (GUARD,HISTORY) else name,root,private=name in (GUARD,HISTORY))


def capture_history(root):
    root=Path(root)
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True,encoding='utf8').strip()
    path=output(HISTORY,root)
    if not path.exists():
        entries=[]
        for n in EVIDENCE:
            commit=git('log','-1','--format=%H','--',n)
            if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Historical evidence has no commit')
            entries.append({'path':n,'last_change_commit':commit,
                'working_source':files.descriptor(root/n,root)})
        value={'repository_head_at_capture':git('rev-parse','HEAD'),
            'scope':'current_tracked_artifacts_and_selected_local_receipts_not_external_or_unlogged_usage',
            'evidence_files':entries,'unlogged_usage_ruled_out':False}
        files.immutable_write(path,files.json_bytes(value))
    history=files.read_json(path)
    if [v['path'] for v in history['evidence_files']]!=list(EVIDENCE):raise ValueError('Usage history paths changed')
    files.verify_sources([v['working_source'] for v in history['evidence_files']],root)
    return history,files.descriptor(path,root)


def verify_history(root):
    path=output(HISTORY,root)
    if not path.is_file():raise ValueError('Original frozen usage-history evidence is required')
    return capture_history(root)


def usage_ledger(root,history):
    root=Path(root)
    dataset=files.read_json(root/'reports/stage5/review_dataset_specification.json')
    base=files.read_json(root/'reports/stage5/review_baseline_training.json')
    treatment=files.read_json(root/'reports/stage5/review_month_ablation_training.json')
    stage4=files.read_json(root/'reports/stage4/monthly_error_diagnostics.json')
    outer=[v['outer_fold'] for v in base['results']['outer_folds']]
    inner=[v['inner_query_start'][:7] for v in dataset['calendar_split_plan']]
    if (dataset['protocol']['cohort']['approval_cutoff_exclusive']!='2018-05-01'
            or dataset['protocol']['observation_cutoff_exclusive']!='2018-07-01'
            or outer!=['2017-12','2018-02','2018-04']
            or [v['outer_fold'] for v in treatment['results']['outer_folds']]!=outer):
        raise ValueError('Historical Stage5 calendar changed')
    sql=(root/'sql/03_business_analysis.sql').read_text(encoding='utf8')
    statements=[v for v in sql.split(';') if re.search(r'FROM\s+order_reviews\b',v,re.I)]
    notebook=files.read_json(root/'notebooks/03_olist_business_analysis.ipynb')
    cells=[''.join(c.get('source',[])) for c in notebook['cells'] if c.get('cell_type')=='code']
    review_cells=[v for v in cells if 'FROM order_reviews' in v]
    if (len(statements)!=1 or re.search(r'\bWHERE\b',statements[0],re.I)
            or len(review_cells)!=1 or re.search(r'\bWHERE\b',review_cells[0],re.I)
            or 'review_score' not in statements[0] or 'GROUP BY review_score' not in review_cells[0]):
        raise ValueError('Source-wide Stage3 review aggregation evidence changed')
    commits={v['path']:v['last_change_commit'] for v in history['evidence_files']}
    return {'stage5_inner_months':inner,'stage5_outer_months':outer,
        'stage5_global_labels_end_exclusive':'2018-05-01',
        'stage5_original_label_cutoff_exclusive':'2018-07-01',
        'stage5_baseline_completed_fits':base['results']['execution']['estimator_fits_completed'],
        'stage5_treatment_completed_fits':treatment['results']['execution']['estimator_fits_completed'],
        'stage4_test_start':stage4['split']['test_start'],
        'stage4_test_last_prediction':stage4['split']['partitions']['test']['prediction_time_max'],
        'stage4_test_months':[v['month'] for v in stage4['test_months']],
        'stage4_target_is_review_score':False,
        'stage3_source_wide_review_aggregation':True,
        'stage3_exposure_is_month_specific_H60_performance':False,
        'historical_selection_records_complete_outside_this_repository':False,
        'evidence':[{'path':n,'last_change_commit':commits[n]} for n in EVIDENCE],
        'interpretation':'No direct Stage5 selection record for later months; source-wide review aggregates and other-task evaluation were already viewed. This does not prove pristine or unlogged nonuse.'}


def load_sources(root,freeze_history=False):
    root=Path(root).resolve()
    parents=[files.descriptor(root/n,root) for n in PINS]
    if any(v['sha256']!=PINS[v['path']] for v in parents):raise ValueError('Frozen mature-prior parent changed')
    spec=files.read_json(root/PARENT_SPEC);report=files.read_json(root/PARENT_REPORT)
    verify=files.read_json(root/PARENT_VERIFY);gp=spec['private_source_guard']['path']
    guard=files.read_json(root/gp);source=files.descriptor(root/PARENT_SPEC,root)
    if (gp!='.runtime/stage5_review_mature_prior_v1/input_guard.json'
            or guard['specification']!=source or report['specification']!=source
            or report['status']!='completed_read_only_mature_prior_temporal_audit'
            or verify['status']!='passed_read_only_mature_prior_verification'
            or spec['private_source_guard']['input_paths']!=[v['path'] for v in guard['private_sources']]):
        raise ValueError('Mature-prior source guard or report differs')
    files.verify_sources(spec['public_sources']+guard['private_sources']+parents,root)
    bundle=sources.load_verified_sources(root)
    history,hd=(capture_history(root) if freeze_history else verify_history(root))
    usage=usage_ledger(root,history)
    public=sources.merge_sources(bundle.public_sources,spec['public_sources'],parents,
        [files.descriptor(root/n,root) for n in EVIDENCE])
    private=sources.merge_sources(bundle.private_sources,guard['private_sources'],
        [files.descriptor(root/n,root) for n in (gp,SOURCE_METADATA)],[hd])
    files.verify_sources(public+private,root)
    return bundle,public,private,usage


def make_specification(public,private,usage,root):
    bound=sources.merge_sources(public,[files.descriptor(Path(root)/n,root) for n in CODE])
    return {'format_version':1,'role':'validation_window_inventory_and_conditional_purpose_freeze',
        'protocol':core.inventory_protocol(),'historical_usage_ledger':usage,'public_sources':bound,
        'private_source_guard':{'path':GUARD,'input_paths':[v['path'] for v in private],'private_digests_public':False},
        'future_validation_gates':['complete_same_ID_approval_roster_for_new_window',
            'accepted_observation_cutoff_at_or_after_calendar_H60_bound_with_completion_and_late_arrival_evidence',
            'original_ingestion_availability_and_review_revision_version_contract',
            'new_versioned_H60_label_bundle_roles_unknown_policy_and_source_guard',
            'freeze_model_features_C_selection_thresholds_metrics_and_read_once_policy_before_any_validation_scores',
            'declare_prior_aggregate_and_cross_task_exposure_and_no_pristine_holdout_claim'],
        'software_versions':sources.baseline.software_versions(),
        'output':REPORT,'new_training':False,'dashboard':False,
        'stage4':{'status':'pending_data','daily_budget':.1,'seeds':[11,29,42,73,101],'modified':False}}


def run(root=ROOT,specification_only=False):
    root=Path(root).resolve()
    with forbid_execution() as calls:
        bundle,public,private,usage=load_sources(root,freeze_history=specification_only)
        expected=make_specification(public,private,usage,root)
        if specification_only:
            payload=files.json_bytes(expected);sd={'path':SPEC,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
            gd=files.json_bytes({'format_version':1,'specification':sd,'private_sources':private})
            targets=[(output(SPEC,root),payload),(output(GUARD,root),gd)]
            for p,b in targets:files.immutable_preflight(p,b)
            files.verify_sources(expected['public_sources']+private,root)
            for p,b in targets:files.immutable_write(p,b)
            files.verify_sources(expected['public_sources']+private+[sd],root)
            return expected
        spec=files.read_json(output(SPEC,root));sd=files.descriptor(root/SPEC,root)
        guard=files.read_json(output(GUARD,root))
        if spec!=expected or guard!={'format_version':1,'specification':sd,'private_sources':private}:
            raise ValueError('Frozen window scope, code or evidence changed')
        bound=spec['public_sources']+private+[sd,files.descriptor(root/GUARD,root)]
        files.verify_sources(bound,root)
        with (root/files.REVIEWS).open(encoding='utf8',newline='') as f:header=next(csv.reader(f))
        if not set(core.REVIEW_COLUMNS+('review_score',)).issubset(header):raise ValueError('Review label schema missing')
        metadata=pd.read_csv(root/files.REVIEWS,usecols=list(core.REVIEW_COLUMNS),dtype='string')
        metadata=metadata.loc[:,list(core.REVIEW_COLUMNS)]
        membership=bundle.membership.loc[:,list(core.MEMBER_COLUMNS)]
        result=core.inventory(bundle.raw_orders,metadata,membership,usage)
        saved=files.read_json(root/SOURCE_METADATA)
        version_sources=[v for v in saved.get('public_sources',[]) if v.get('id')=='olist_ecommerce_card']
        if len(version_sources)!=1:raise ValueError('Saved version evidence missing')
        version=version_sources[0]
        version_summary={k:version[k] for k in ['id','live_current_version_field','live_last_updated','version_caution']}
        bundle.verify_stable();files.verify_sources(bound,root)
        if calls['forbidden_calls']:raise RuntimeError('Forbidden execution prevents publication')
        report={'format_version':1,'status':'completed_metadata_window_inventory_pending_data',
            'specification':sd,'protocol':spec['protocol'],'sources':spec['public_sources'],
            'historical_usage_ledger':usage,'inventory':result,
            'version_support':{'saved_official_metadata':version_summary,
                'live_web_or_DB_rechecked':False,'new_accepted_observation_cutoff':None,
                'original_ingestion_and_revision_versions_verified':False,
                'new_label_bundle_created':False,'status':'pending_data'},
            'frozen_future_use':{'old_cohort':'development_only','later_cohort':'quarantined_future_retrospective_temporal_validation_pending_data',
                'model_or_feature_selection_on_later_labels':False,'pristine_unseen_claim':False,
                'required_gates':spec['future_validation_gates'],'scoring_authorized_this_step':False},
            'verification':{'public_bindings':len(spec['public_sources']),'private_bindings':len(private),
                'score_values_read':False,'new_targets_created':False,'raw_review_score_values_read':False,
                'historical_role_blocks':12,'historical_membership_rows':len(membership),
                'new_fits':0,'predictions':0,'performance_metrics':0,'parameter_updates':0,
                'forbidden_execution_attempts':calls['forbidden_calls'],'source_bytes_checked_before_after':True},
            'limitations':['Current repository and selected local evidence cannot prove absence of external or unlogged usage.',
                'Source-wide score aggregation is prior exposure, not month-specific Stage5 H60 selection.',
                'Other-task test usage does not establish review-model performance or automatically equal review-label selection.',
                'An event timestamp maximum, a linked review row, or a source byte hash proves no complete observation window.',
                'Later score validity, first-answer target quality, class support and new roles have not been accepted.',
                'Missing approval clocks cannot be assigned by purchase date; full-source completeness remains unverified.'],
            'stage4':spec['stage4'],'dashboard':False}
        data=files.json_bytes(report);path=output(REPORT,root);files.immutable_preflight(path,data);existed=path.exists()
        try:
            files.immutable_write(path,data)
            if path.read_bytes()!=data:raise ValueError('Window inventory readback differs')
            files.verify_sources(bound,root);bundle.verify_stable()
        except Exception:
            if not existed and path.is_file() and path.read_bytes()==data:path.unlink()
            raise
        return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--specification-only',action='store_true')
    args=p.parse_args(argv);r=run(specification_only=args.specification_only)
    print(r.get('status','frozen_validation_window_inventory_and_conditional_purpose'))


if __name__=='__main__':main()
