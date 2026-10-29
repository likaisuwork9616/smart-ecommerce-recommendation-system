"""Freeze D1 implementation or run one guarded validation; no final/test mode."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import unittest
import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import retailrocket_directed_io as adapter
from scripts import retailrocket_directed_oracle as oracle
from scripts import retailrocket_directed_cost as cost_module
from scripts import freeze_retailrocket_directed_v1 as specification
from scripts import retailrocket_popularity_io as old

POLICY='docs/contracts/retailrocket_directed_paired_v1.json'
PARENT='docs/contracts/retailrocket_recommendation_v1.json'
UPSTREAM='shop-mysql-runtime/retailrocket_directed_spec_v1/output_guard.json'
PRIVATE='shop-mysql-runtime/retailrocket_directed_implementation_v1'
VERIFY='shop-mysql-runtime/verification/retailrocket-directed-implementation-v1'
DEV='shop-mysql-runtime/retailrocket_directed_paired_v1'
SPEC='reports/stage11/retailrocket_directed_v1_validation_specification.json'
ACCEPT='reports/stage11/retailrocket_directed_v1_implementation_acceptance.json'
RESULT='reports/stage11/retailrocket_directed_v1_validation.json'
REAL_ACCEPT='reports/stage11/retailrocket_directed_v1_validation_acceptance.json'
DOC='docs/STAGE11_RETAILROCKET_DIRECTED_IMPLEMENTATION_V1.md'
CODE=['scripts/retailrocket_directed.py','scripts/retailrocket_directed_io.py','scripts/retailrocket_directed_oracle.py',
      'scripts/retailrocket_directed_cost.py','scripts/run_retailrocket_directed_v1.py',
      'tests/test_retailrocket_directed.py','tests/test_retailrocket_directed_entry.py']
LIMITS={'maximum_process_RSS_bytes':8*1024**3,'maximum_execution_disk_bytes':20*1024**3,
        'minimum_free_disk_bytes':8*1024**3,'minimum_available_memory_bytes':4*1024**3,
        'maximum_elapsed_seconds':21600,'monitor_interval_seconds':0.5}


def inside(relative):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise ValueError('Every artifact must resolve inside shop')
    return path


def descriptor(relative):
    path=inside(relative)
    with path.open('rb') as stream:h=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':h}


def check(records):
    for r in records:
        if descriptor(r['path'])!={k:r[k] for k in ('path','bytes','sha256')}:raise ValueError('Frozen bytes changed: '+r['path'])


def read(relative):return json.loads(inside(relative).read_text(encoding='utf-8'))


def write_new(relative,value):
    p=inside(relative);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


def state(folder):
    if not folder.exists():return 'absent'
    if (folder/'failure.json').exists():return 'partial'
    return 'complete' if (folder/'output_guard.json').is_file() else 'partial'


def require_locked(gate,base):
    if (gate.get('state')!='locked' or gate.get('D1_test_authorized') is not False
        or type(gate.get('logical_test_runs_consumed_this_round')) is not int or gate['logical_test_runs_consumed_this_round']!=0):
        raise ValueError('D1 gate must remain locked')
    forbidden=['retailrocket_cooccurrence_final_v1','retailrocket_directed_final_v1']
    forbidden += [f'{root}/{name}' for root in ('retailrocket_popularity_v1','retailrocket_directed_paired_v1')
                  for name in ('reserved_test','final_refit','test_usage.jsonl')]
    for name in forbidden:
        if (base/name).exists():raise ValueError('Final/test namespace forbidden: '+name)


def validate_measurements(v):
    if v['RSS']>LIMITS['maximum_process_RSS_bytes']:raise RuntimeError('RSS limit exceeded')
    if v['disk']>LIMITS['maximum_execution_disk_bytes']:raise RuntimeError('Execution disk limit exceeded')
    if v['free_disk']<LIMITS['minimum_free_disk_bytes']:raise RuntimeError('Free disk below floor')
    if v['available_memory']<LIMITS['minimum_available_memory_bytes']:raise RuntimeError('Available memory below floor')
    if v['elapsed']>LIMITS['maximum_elapsed_seconds']:raise RuntimeError('Execution time limit exceeded')


class Budget:
    def __init__(self,folder):self.folder=folder;self.started=time.monotonic();self.last=float('-inf');self.peak=0;self.samples=0
    def __call__(self):
        now=time.monotonic()
        if now-self.last<LIMITS['monitor_interval_seconds']:return
        self.last=now
        values={'RSS':psutil.Process().memory_info().rss,'disk':sum(p.stat().st_size for p in self.folder.rglob('*') if p.is_file()),
          'free_disk':shutil.disk_usage(self.folder).free,'available_memory':psutil.virtual_memory().available,'elapsed':now-self.started}
        self.peak=max(self.peak,values['RSS']);self.samples+=1;validate_measurements(values)
    def receipt(self):
        self.last=float('-inf');self()
        return {'elapsed_seconds':round(time.monotonic()-self.started,6),'observed_peak_sampled_RSS_bytes':self.peak,'samples':self.samples,
          'limits':LIMITS,'enforcement':'cooperative 0.5s checks; per-session/query/replicate and bounded edge-loop/SQL progress callbacks; not OS-hard instantaneous limits'}


def sources(include_cost=True):
    guard=read(UPSTREAM);bound={r['path']:r for r in guard['sources']+guard['outputs']};check(list(bound.values()))
    names=[UPSTREAM,*CODE,DOC,Path(sys.executable).resolve().relative_to(ROOT).as_posix(),'.venv/pyvenv.cfg']
    for module in (np,importlib.import_module('numpy.random._pcg64'),importlib.import_module('numpy._core._multiarray_umath'),
                   psutil,importlib.import_module('psutil._psutil_windows')):
        names.append(Path(module.__file__).resolve().relative_to(ROOT).as_posix())
    names.append('.venv/Lib/site-packages/psutil-7.2.2.dist-info/METADATA')
    if include_cost:names.extend(p.relative_to(ROOT).as_posix() for p in sorted(inside(VERIFY+'/train_cost').rglob('*')) if p.is_file())
    for name in names:bound[name]=descriptor(name)
    return [bound[k] for k in sorted(bound)]


def prepare():
    if state(inside(PRIVATE))=='complete':return verify_prepared()
    if state(inside(PRIVATE))=='partial' or any(inside(p).exists() for p in (SPEC,ACCEPT,DEV,RESULT,REAL_ACCEPT,VERIFY+'/tests.log',VERIFY+'/train_cost')):
        raise FileExistsError('Existing or partial D1 preparation preserved; no overwrite')
    specification.check_locked_scope(freeze_only=True)
    gate=read('shop-mysql-runtime/retailrocket_directed_spec_v1/initial_locked_scope.json')
    require_locked(gate,inside('shop-mysql-runtime'))
    if read(POLICY)['resources_and_next_entry']['limits']!=LIMITS:raise ValueError('Frozen budget differs')
    initial=sources(False);inside(PRIVATE).mkdir(parents=True);inside(VERIFY).mkdir(parents=True,exist_ok=True)
    write_new(PRIVATE+'/started.json',{'operation':'D1_implementation_synthetic_cost_and_entry_freeze','real_model_execution':False})
    started=time.perf_counter();budget=Budget(inside(VERIFY))
    try:
        budget();log=io.StringIO()
        suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_retailrocket_directed','tests.test_retailrocket_directed_entry'])
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        with inside(VERIFY+'/tests.log').open('x',encoding='utf-8',newline='\n') as f:f.write(log.getvalue())
        if not outcome.wasSuccessful() or outcome.skipped:raise ValueError('D1 synthetic/entry tests failed; evidence preserved')
        from tests.test_retailrocket_directed import fixture,SCHEMAS,PARENT as toy_parent
        cases=[]
        for name,brute in [('hand_and_full_catalog',True),('exact_sparse_complement',False)]:
            root,source,baseline,c1_ref,output,policy,p0_result,c1_result,_=fixture(base=inside(VERIFY+'/acceptance'))
            primary=adapter.build(output,source,baseline,c1_ref,SCHEMAS,policy,toy_parent,p0_result['aggregate'],c1_result['aggregate']['arms']['C1'],budget)
            independent=oracle.verify(output,source,baseline,c1_ref,SCHEMAS,policy,toy_parent,brute=brute,watch=budget)
            oracle.close(primary['aggregate'],independent['aggregate'])
            files=[descriptor(p.relative_to(ROOT).as_posix()) for p in sorted(root.rglob('*')) if p.is_file()]
            cases.append({'case':name,'kind':'synthetic_only','queries':primary['aggregate']['arms']['D1']['queries'],
              'all_nested_values_checked':True,'bootstrap_replicates_replayed':2000,'ranking_oracle':independent['ranking_oracle'],
              'readback':{k:v for k,v in independent.items() if k not in ('aggregate','fit_audit')},'files':files})
        # First real semantic pass of this round is train-only cost, after all synthetic acceptance.
        policy=read(POLICY);schemas=read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
        cost_start=time.perf_counter()
        cost=cost_module.audit(inside('shop-mysql-runtime/retailrocket_dataset_v1/baskets.csv'),schemas['baskets.csv'],
             old.ms(policy['comparison']['fit_start_inclusive_utc']),old.ms(policy['comparison']['fit_end_exclusive_utc']),inside(VERIFY+'/train_cost'),budget)
        cost_seconds=round(time.perf_counter()-cost_start,6)
        old_cost=read('reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json')['train_only_cost']
        for k in ('train_sessions','singleton_sessions','train_baskets','basket_item_memberships','distinct_session_item_memberships'):
            if cost[k]!=old_cost[k]:raise ValueError('Train population changed: '+k)
        if cost['session_unique_directed_emissions']>2*old_cost['exact_unordered_pair_emissions']:raise ValueError('D1 per-session edge bound failed')
        if cost['global_directed_count_model_built'] or cost['item_support_model_built'] or cost['validation_or_test_items_decoded']:raise ValueError('Cost scope exceeded')
        usage=budget.receipt();write_new(VERIFY+'/train_cost/resources.json',dict(usage,cost_elapsed_seconds=cost_seconds))
        check(initial);specification.check_locked_scope(freeze_only=True);bound=sources(True)
        scope={'D1_three_arm_and_bootstrap_implemented':True,'synthetic_acceptance_passed':True,'real_D1_primary_fits':0,
          'new_P0_fits_or_rerankings':0,'new_C1_fits_or_rerankings':0,'real_validation_ranked_queries':0,
          'real_paired_metrics':0,'real_bootstrap_replicates':0,'train_only_cost_audit':True,'independent_cost_passes':2,
          'real_train_baskets_parsed_per_cost_pass':cost['train_baskets'],'real_validation_or_test_items_decoded_this_round':False,
          'reserved_test_state':'locked','final_refit_or_test_entry_implemented':False}
        frozen_gate={'state':'locked','D1_test_authorized':False,'logical_test_runs_consumed_this_round':0,
          'allowed_real_operation':'--run-validation only after separate requested scope; cannot reuse P0/C1 test gate'}
        write_new(PRIVATE+'/test_gate_snapshot.json',frozen_gate)
        environment={'python':platform.python_version(),'numpy':np.__version__,'psutil':psutil.__version__,
          'total_memory_bytes':psutil.virtual_memory().total,'available_memory_bytes':psutil.virtual_memory().available,'free_disk_bytes':shutil.disk_usage(ROOT).free}
        tests={'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped)}
        spec={'status':'real_D1_three_arm_validation_entry_frozen_not_executed','date_asia_taipei':'2026-10-28',
          'sources':bound,'protocol':descriptor(POLICY),'environment':environment,'resources':LIMITS,'train_only_cost':cost,
          'scope':scope,'tests':tests,'test_gate_snapshot':descriptor(PRIVATE+'/test_gate_snapshot.json'),
          'planned_execution':{'command':'--run-validation','primary_D1_fits':1,'independent_SQL_count_audits':1,
            'P0_C1_refits_or_rerankings':0,'validation_queries':166897,'validation_visitors':62235,'bootstrap_replicates':2000,
            'primary_contrast':'D1-C1 query-macro NDCG','D1_P0':'descriptive only; no interval','output_namespace':DEV,
            'artifacts':list(adapter.ARTIFACTS)+['oracle.sqlite','started.json','resource_usage.json','manifest.json','output_guard.json'],
            'fit_identity':'Exact canonical D1 algorithm/window/shared S and numerically sorted directed edges; implemented independently in oracle',
            'ranking_proof':'all outgoing evidence plus complete P0-ordered zero complement, exact fractions and strict causal catalog',
            'oracle':'independent SQL adjacent joins and per-session directed DISTINCT, shared S reconstruction, all lineage/queries/nested values and bootstrap draw/new-delta replay',
            'failure':'Stop and preserve partial evidence on limits or identity/denominator/readback failure; no truncation/sampling/retry',
            'unmeasured':'Real global unique D1 edges, model RSS, validation history/neighbor workload, full runtime and D1 performance remain unknown',
            'exposure':'P0 and C1 validation observed before D1 selection; no pristine holdout claim'}}
        write_new(SPEC,spec)
        acceptance={'status':'D1_three_arm_bootstrap_hand_and_independent_synthetic_passed_entry_frozen','specification':descriptor(SPEC),
          'sources_verified':len(bound),'tests':tests,'synthetic_cases':cases,'train_only_cost':cost,'cost_elapsed_seconds':cost_seconds,
          'preparation_resources':usage,'resources':LIMITS,'scope':scope,'elapsed_seconds':round(time.perf_counter()-started,6),
          'next_step':'Later explicitly execute one --run-validation and complete independent readback; keep final/test locked'}
        write_new(ACCEPT,acceptance)
        outputs=[descriptor(p) for p in (SPEC,ACCEPT,PRIVATE+'/started.json',PRIVATE+'/test_gate_snapshot.json',VERIFY+'/tests.log')]
        for case in cases:outputs.extend(case['files'])
        write_new(PRIVATE+'/output_guard.json',{'sources':bound,'outputs':outputs})
        if read(SPEC)!=spec or read(ACCEPT)!=acceptance:raise ValueError('Frozen JSON readback differs')
        check(bound+outputs)
        return {'status':acceptance['status'],'sources_verified':len(bound),'tests':tests,'train_only_cost':cost,'scope':scope}
    except Exception as error:
        write_new(PRIVATE+'/failure.json',{'status':'partial_preparation_preserved','error':str(error),'real_D1_fit_attempts':0})
        raise


def verify_prepared():
    if state(inside(PRIVATE))!='complete':raise ValueError('D1 preparation not complete')
    guard=read(PRIVATE+'/output_guard.json');check(guard['sources']+guard['outputs'])
    require_locked(read(PRIVATE+'/test_gate_snapshot.json'),inside('shop-mysql-runtime'));specification.check_locked_scope(False)
    return {'status':'prepared_D1_sources_synthetic_cost_and_entry_verified','sources_verified':len(guard['sources']),
      'research_recomputed':False,'scope_at_prepare':read(ACCEPT)['scope']}


def verify_real():
    guard=read(DEV+'/output_guard.json');check(guard['sources']+guard['outputs'])
    require_locked(read(PRIVATE+'/test_gate_snapshot.json'),inside('shop-mysql-runtime'));specification.check_locked_scope(False)
    return {'status':'existing_D1_three_arm_validation_bytes_verified','research_recomputed':False}


def run_validation():
    current=state(inside(DEV))
    if current=='complete':return verify_real()
    if current=='partial':raise FileExistsError('Partial D1 execution preserved; no replay')
    if state(inside(PRIVATE))!='complete':raise ValueError('Prepare/freeze synthetic acceptance first')
    verify_prepared();require_locked(read(PRIVATE+'/test_gate_snapshot.json'),inside('shop-mysql-runtime'))
    if any(inside(p).exists() for p in (RESULT,REAL_ACCEPT)):raise FileExistsError('Existing real result preserved')
    folder=inside(DEV);folder.mkdir(parents=True)
    write_new(DEV+'/started.json',{'operation':'one_D1_train_fit_three_arm_validation','D1_primary_fit_attempts':1,
      'specification':descriptor(SPEC),'reserved_test':'locked'})
    budget=Budget(folder)
    try:
        budget();spec=read(SPEC);policy=read(POLICY);parent=read(PARENT)
        schemas=read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
        source=inside('shop-mysql-runtime/retailrocket_dataset_v1');baseline=inside('shop-mysql-runtime/retailrocket_popularity_v1/development')
        c1_ref=inside('shop-mysql-runtime/retailrocket_cooccurrence_paired_v1')
        p0=read('reports/stage9/retailrocket_popularity_v1_development.json')['validation']
        c1=read('reports/stage10/retailrocket_cooccurrence_v1_validation.json')['validation']
        primary=adapter.build(folder,source,baseline,c1_ref,schemas,policy,parent,p0,c1['arms']['C1'],budget)
        independent=oracle.verify(folder,source,baseline,c1_ref,schemas,policy,parent,watch=budget)
        oracle.close(primary['aggregate'],independent['aggregate'])
        cost_keys={k:k for k in ('train_sessions','singleton_sessions','train_baskets','basket_item_memberships','distinct_session_item_memberships','raw_directed_emissions')}
        cost_keys.update(eligible_adjacent_pairs='eligible_adjacent_basket_pairs',session_unique_directed_emissions='distinct_session_directed_edges')
        for ck,fk in cost_keys.items():
            if primary['fit_audit'][fk]!=spec['train_only_cost'][ck]:raise ValueError('D1 fit/cost audit differ: '+ck)
        check(spec['sources']);require_locked(read(PRIVATE+'/test_gate_snapshot.json'),inside('shop-mysql-runtime'));specification.check_locked_scope(False)
        usage=budget.receipt();write_new(DEV+'/resource_usage.json',usage)
        files=[descriptor(DEV+'/'+n) for n in (*adapter.ARTIFACTS,'oracle.sqlite','resource_usage.json','started.json')]
        scope={'real_D1_primary_fits':1,'real_independent_count_audits':1,'P0_C1_refits_or_rerankings':0,'validation_queries':166897,
          'training_ranked_queries':0,'reserved_test_ranked_queries':0,'final_refits':0,'reserved_test_state':'locked'}
        result={'status':'D1_three_arm_validation_and_bootstrap_independently_accepted','specification':descriptor(SPEC),
          'scope':scope,'fit_audit':primary['fit_audit'],'validation':primary['aggregate'],'files':files,'resources':usage}
        write_new(RESULT,result)
        write_new(REAL_ACCEPT,{'status':'complete_D1_counts_lineage_three_arm_queries_and_bootstrap_accepted','result':descriptor(RESULT),
          'scope':scope,'readback':{k:v for k,v in independent.items() if k not in ('aggregate','fit_audit')}})
        write_new(DEV+'/manifest.json',{'status':'accepted','files':files,'specification':descriptor(SPEC),'scope':scope})
        frozen_inputs=spec['sources']+[descriptor(p) for p in (SPEC,ACCEPT,PRIVATE+'/output_guard.json')]
        outputs=files+[descriptor(p) for p in (RESULT,REAL_ACCEPT,DEV+'/manifest.json')]
        write_new(DEV+'/output_guard.json',{'sources':frozen_inputs,'outputs':outputs});check(outputs)
        return {'status':result['status'],'scope':scope,'uncertainty':primary['aggregate']['uncertainty']}
    except Exception as error:
        write_new(DEV+'/failure.json',{'status':'partial_D1_execution_preserved','error':str(error),'D1_primary_fit_attempts':1,'reserved_test':'locked'})
        raise


def parser():
    result=argparse.ArgumentParser(description=__doc__);group=result.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--run-validation',action='store_true');group.add_argument('--verify',action='store_true')
    return result


def verify():
    if state(inside(DEV))=='partial':raise FileExistsError('Partial execution is not preparation success')
    return verify_real() if state(inside(DEV))=='complete' else verify_prepared()


if __name__=='__main__':
    args=parser().parse_args();print(json.dumps(prepare() if args.prepare else run_validation() if args.run_validation else verify(),ensure_ascii=False,indent=2,allow_nan=False))
