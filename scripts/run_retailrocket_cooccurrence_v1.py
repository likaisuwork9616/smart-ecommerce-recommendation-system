"""Prepare or execute one C1 train fit + paired validation; no test command."""
from __future__ import annotations
import argparse
import contextlib
import importlib
import hashlib
import io as textio
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import unittest
import psutil
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import retailrocket_cooccurrence_io as adapter
from scripts import retailrocket_cooccurrence_oracle as oracle

POLICY='docs/contracts/retailrocket_cooccurrence_paired_v1.json'
PARENT='docs/contracts/retailrocket_recommendation_v1.json'
UPSTREAM='shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/output_guard.json'
PRIVATE='shop-mysql-runtime/retailrocket_cooccurrence_implementation_v1'
VERIFY='shop-mysql-runtime/verification/retailrocket-cooccurrence-implementation-v1'
DEV='shop-mysql-runtime/retailrocket_cooccurrence_paired_v1'
SPEC='reports/stage10/retailrocket_cooccurrence_v1_validation_specification.json'
ACCEPT='reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json'
RESULT='reports/stage10/retailrocket_cooccurrence_v1_validation.json'
REAL_ACCEPT='reports/stage10/retailrocket_cooccurrence_v1_validation_acceptance.json'
DOC='docs/STAGE10_RETAILROCKET_COOCCURRENCE_IMPLEMENTATION_V1.md'
CODE=['scripts/retailrocket_cooccurrence.py','scripts/retailrocket_cooccurrence_io.py',
      'scripts/retailrocket_cooccurrence_oracle.py','scripts/retailrocket_cooccurrence_cost.py',
      'scripts/run_retailrocket_cooccurrence_v1.py','tests/test_retailrocket_cooccurrence.py',
      'tests/test_retailrocket_cooccurrence_entry.py']
LIMITS={'maximum_process_RSS_bytes':8*1024**3,'maximum_execution_disk_bytes':20*1024**3,
        'minimum_free_disk_bytes':8*1024**3,'minimum_available_memory_bytes':4*1024**3,
        'maximum_elapsed_seconds':21600,'monitor_interval_seconds':0.5}


def inside(relative):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Every artifact must resolve inside shop')
    return path


def descriptor(relative):
    path=inside(relative);digest=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):digest.update(block)
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':digest.hexdigest()}


def check(records):
    for record in records:
        if descriptor(record['path'])!=record:raise ValueError('Frozen source/output bytes changed: '+record['path'])


def read(relative):return json.loads(inside(relative).read_text(encoding='utf-8'))


def write_new(relative,value):
    path=inside(relative);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


def state(folder):
    if not folder.exists():return 'absent'
    return 'complete' if (folder/'output_guard.json').is_file() else 'partial'


def require_locked(gate,base):
    if gate.get('state')!='locked' or gate.get('C1_test_authorized') is not False or gate.get('logical_test_runs_consumed_this_round')!=0:
        raise ValueError('C1 specification test gate must be locked')
    for parent in (base/'retailrocket_popularity_v1',base/'retailrocket_cooccurrence_final_v1'):
        for name in ('reserved_test','final_refit','test_usage.jsonl'):
            if (parent/name).exists():raise ValueError('Test/final evidence exists; entry remains validation-only')


def validate_measurements(values):
    if values['RSS']>LIMITS['maximum_process_RSS_bytes']:raise RuntimeError('RSS limit exceeded')
    if values['disk']>LIMITS['maximum_execution_disk_bytes']:raise RuntimeError('Execution disk limit exceeded')
    if values['free_disk']<LIMITS['minimum_free_disk_bytes']:raise RuntimeError('Free disk below floor')
    if values['available_memory']<LIMITS['minimum_available_memory_bytes']:raise RuntimeError('Available memory below floor')
    if values['elapsed']>LIMITS['maximum_elapsed_seconds']:raise RuntimeError('Execution time limit exceeded')


class Budget:
    def __init__(self,folder):
        self.folder=folder;self.started=time.monotonic();self.last=float('-inf');self.peak=0;self.samples=0
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
                'limits':LIMITS,'enforcement':'cooperative checks at most every 0.5 seconds; pair loop also checks every 50000 emissions; no OS hard-memory kill'}


def sources():
    upstream=read(UPSTREAM);bound={r['path']:r for r in upstream['sources']+upstream['outputs']};check(list(bound.values()))
    paths=[UPSTREAM,*CODE,DOC]
    paths.extend(p.relative_to(ROOT).as_posix() for p in sorted(inside(VERIFY+'/train_cost').rglob('*')) if p.is_file())
    paths.extend([Path(sys.executable).resolve().relative_to(ROOT).as_posix(),'.venv/pyvenv.cfg'])
    for module in (np,importlib.import_module('numpy.random._pcg64'),importlib.import_module('numpy._core._multiarray_umath'),psutil,importlib.import_module('psutil._psutil_windows')):
        paths.append(Path(module.__file__).resolve().relative_to(ROOT).as_posix())
    paths.append('.venv/Lib/site-packages/psutil-7.2.2.dist-info/METADATA')
    for path in paths:bound[path]=descriptor(path)
    return [bound[k] for k in sorted(bound)]


def prepare():
    if state(inside(PRIVATE))=='complete':return verify_prepared()
    if state(inside(PRIVATE))=='partial' or any(inside(p).exists() for p in (SPEC,ACCEPT,DEV,RESULT,REAL_ACCEPT,VERIFY+'/tests.log')):
        raise FileExistsError('Existing or partial preparation preserved; no overwrite')
    require_locked(read('shop-mysql-runtime/retailrocket_cooccurrence_spec_v1/initial_locked_scope.json'),inside('shop-mysql-runtime'))
    bound=sources();log=textio.StringIO();started=time.perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_retailrocket_cooccurrence','tests.test_retailrocket_cooccurrence_entry'])
    with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    if not outcome.wasSuccessful() or outcome.skipped:
        print(log.getvalue());raise ValueError('Synthetic acceptance failed')
    from tests.test_retailrocket_cooccurrence import fixture,SCHEMAS,PARENT as parent
    synthetic=[]
    for name,brute in [('hand_and_full_catalog',True),('exact_sparse_complement',False)]:
        root,source,baseline,output,policy,original,_=fixture(base=inside(VERIFY+'/acceptance'))
        primary=adapter.build(output,source,baseline,SCHEMAS,policy,parent,original['aggregate'])
        independent=oracle.verify(output,source,baseline,SCHEMAS,policy,parent,brute=brute)
        oracle.close(primary['aggregate'],independent['aggregate'])
        files=[descriptor(p.relative_to(ROOT).as_posix()) for p in sorted(root.rglob('*')) if p.is_file()]
        synthetic.append({'case':name,'kind':'synthetic_only','queries':primary['aggregate']['paired']['queries'],
            'independent_readback_rows':independent['rows'],'top_level_cells':independent['top_level_cells'],
            'all_nested_JSON_values_checked':True,'ranking_oracle':independent['ranking_oracle'],'bootstrap_replicates_replayed':2000,
            'hand_first_query':{'C1_top3':['2','3','1'],'C1_recall':.5,'C1_ndcg':next(oracle.jsonlines(output/'queries.jsonl'))['terms']['C1']['ndcg']},
            'files':files})
    check(bound)
    cost=read(VERIFY+'/train_cost/cost.json')
    if cost['pair_count_model_built'] or cost['item_support_model_built'] or cost['validation_or_test_items_decoded']:
        raise ValueError('Cost audit exceeded training-only no-model scope')
    scope={'C1_and_paired_and_bootstrap_implemented':True,'synthetic_acceptance_passed':True,
           'real_C1_fits':0,'new_real_P0_fits':0,'real_validation_ranked_queries':0,'real_paired_metrics':0,'real_bootstrap_replicates':0,
           'train_only_cost_audit':True,'real_train_baskets_parsed_per_cost_pass':cost['train_baskets'],'independent_cost_passes':2,
           'real_validation_or_test_items_decoded_this_round':False,'reserved_test_state':'locked','final_refit_or_test_entry_implemented':False}
    inside(PRIVATE).mkdir();inside(VERIFY).mkdir(parents=True,exist_ok=True)
    with inside(VERIFY+'/tests.log').open('x',encoding='utf-8',newline='\n') as stream:stream.write(log.getvalue())
    gate={'state':'locked','C1_test_authorized':False,'logical_test_runs_consumed_this_round':0,
          'allowed_real_operation':'--run-validation only; requires this prepared guard; no test/final-refit flags'}
    write_new(PRIVATE+'/test_gate_snapshot.json',gate)
    environment={'python':platform.python_version(),'numpy':np.__version__,'psutil':psutil.__version__,
                 'total_memory_bytes':psutil.virtual_memory().total,'available_memory_bytes':psutil.virtual_memory().available,'free_disk_bytes':shutil.disk_usage(ROOT).free}
    spec={'status':'real_C1_paired_validation_entry_frozen_not_executed','date_asia_taipei':'2026-10-28','sources':bound,
        'protocol':descriptor(POLICY),'environment':environment,'resources':LIMITS,'train_only_cost':cost,
        'scope':scope,'planned_execution':{'command':'--run-validation','primary_C1_fits':1,'independent_SQL_count_audits':1,
            'P0_refits_or_rerankings':0,'validation_queries':166897,'validation_visitors':62235,'bootstrap_replicates':2000,
            'output_namespace':DEV,'artifacts':list(adapter.ARTIFACTS)+['oracle.sqlite','started.json','resource_usage.json','manifest.json','output_guard.json'],
            'fit_identity':'SHA256 algorithm/window line + numeric sorted S and C records; exact format in source and independent oracle',
            'ranking_proof':'all neighbors accumulated as exact fractions, outside neighbor union score zero; full P0-order zero complement, strict causal catalog',
            'oracle':'independent SQL DISTINCT memberships and self-join pair counts, complete lineage/count/query/rational/nested-metric readback and all bootstrap replay',
            'failure':'budget/hash/schema/count/query/finite/readback drift stops; started marker before fit, preserve partial evidence, refuse replay/overwrite',
            'budget_note':'6 hours for build + validation + independent acceptance; 8 GiB sampled process RSS and 20 GiB execution namespace; cooperative checks; no silent approximation',
            'unmeasured':'real C1 model size, validation neighbor/history workload, runtime and scores remain unknown; train-only emissions are not a validation runtime benchmark'},
        'tests':{'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped)},
        'test_gate_snapshot':descriptor(PRIVATE+'/test_gate_snapshot.json')}
    write_new(SPEC,spec)
    acceptance={'status':'C1_paired_bootstrap_hand_independent_synthetic_acceptance_passed_entry_frozen',
        'specification':descriptor(SPEC),'sources_verified':len(bound),'tests':spec['tests'],'synthetic_cases':synthetic,
        'train_only_cost':cost,'resources':LIMITS,'scope':scope,'elapsed_seconds':round(time.perf_counter()-started,6),
        'next_step':'later execute --run-validation once, independently read back all outputs; test stays locked'}
    write_new(ACCEPT,acceptance)
    outputs=[descriptor(p) for p in (SPEC,ACCEPT,PRIVATE+'/test_gate_snapshot.json',VERIFY+'/tests.log')]
    for case in synthetic:outputs.extend(case['files'])
    write_new(PRIVATE+'/output_guard.json',{'sources':bound,'outputs':outputs})
    check(outputs)
    return {'status':acceptance['status'],'sources_verified':len(bound),'tests':spec['tests'],'cost':cost,'scope':scope}


def verify_prepared():
    guard=read(PRIVATE+'/output_guard.json');check(guard['sources']+guard['outputs'])
    return {'status':'prepared_C1_sources_synthetic_evidence_and_cost_verified','sources_verified':len(guard['sources']),
            'fits_or_metrics_recomputed':False,'scope_at_prepare':read(ACCEPT)['scope']}


def verify_real():
    guard=read(DEV+'/output_guard.json');check(guard['sources']+guard['outputs'])
    return {'status':'existing_C1_paired_validation_bytes_verified','fits_or_metrics_recomputed':False}


def run_validation():
    current=state(inside(DEV))
    if current=='complete':return verify_real()
    if current=='partial':raise FileExistsError('Partial C1 execution preserved; no replay')
    if state(inside(PRIVATE))!='complete':raise ValueError('Prepare and freeze synthetic acceptance first')
    verify_prepared();require_locked(read(PRIVATE+'/test_gate_snapshot.json'),inside('shop-mysql-runtime'))
    if any(inside(p).exists() for p in (RESULT,REAL_ACCEPT)):raise FileExistsError('Existing public real result preserved')
    folder=inside(DEV);folder.mkdir()
    write_new(DEV+'/started.json',{'operation':'one_C1_train_fit_and_paired_validation','C1_primary_fit_attempts':1,
        'specification':descriptor(SPEC),'reserved_test':'locked'})
    budget=Budget(folder)
    try:
        budget();spec=read(SPEC);policy=read(POLICY);parent=read(PARENT)
        schemas=read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
        source=inside('shop-mysql-runtime/retailrocket_dataset_v1');baseline=inside('shop-mysql-runtime/retailrocket_popularity_v1/development')
        expected=read('reports/stage9/retailrocket_popularity_v1_development.json')['validation']
        primary=adapter.build(folder,source,baseline,schemas,policy,parent,expected,budget)
        independent=oracle.verify(folder,source,baseline,schemas,policy,parent,watch=budget)
        oracle.close(primary['aggregate'],independent['aggregate'])
        for k in ('train_sessions','singleton_sessions','train_baskets','basket_item_memberships','distinct_session_item_memberships','exact_unordered_pair_emissions'):
            if primary['fit_audit'][k]!=spec['train_only_cost'][k]:raise ValueError('Fit differs from frozen train cost audit')
        check(spec['sources']);require_locked(read(PRIVATE+'/test_gate_snapshot.json'),inside('shop-mysql-runtime'))
        usage=budget.receipt();write_new(DEV+'/resource_usage.json',usage)
        files=[descriptor(DEV+'/'+name) for name in (*adapter.ARTIFACTS,'oracle.sqlite','resource_usage.json','started.json')]
        scope={'real_C1_primary_fits':1,'real_independent_count_audits':1,'P0_refits_or_rerankings':0,
               'validation_queries':166897,'training_ranked_queries':0,'reserved_test_ranked_queries':0,'final_refits':0,'reserved_test_state':'locked'}
        result={'status':'C1_paired_validation_and_bootstrap_independently_accepted','specification':descriptor(SPEC),
                'scope':scope,'fit_audit':primary['fit_audit'],'validation':primary['aggregate'],'files':files,'resources':usage}
        write_new(RESULT,result)
        write_new(REAL_ACCEPT,{'status':'complete_C1_model_lineage_queries_nested_values_and_bootstrap_accepted',
                  'result':descriptor(RESULT),'scope':scope,'readback':{k:v for k,v in independent.items() if k not in ('aggregate','fit_audit')}})
        write_new(DEV+'/manifest.json',{'status':'accepted','files':files,'specification':descriptor(SPEC),'scope':scope})
        frozen_inputs=spec['sources']+[descriptor(p) for p in (SPEC,ACCEPT,PRIVATE+'/output_guard.json')]
        outputs=files+[descriptor(p) for p in (RESULT,REAL_ACCEPT,DEV+'/manifest.json')]
        write_new(DEV+'/output_guard.json',{'sources':frozen_inputs,'outputs':outputs})
        return {'status':result['status'],'scope':scope,'paired':primary['aggregate']['paired'],'uncertainty':primary['aggregate']['uncertainty']}
    except Exception as error:
        write_new(DEV+'/failure.json',{'status':'partial_C1_execution_preserved','error':str(error),'C1_primary_fit_attempts':1,'reserved_test':'locked'})
        raise


def parser():
    result=argparse.ArgumentParser(description=__doc__);group=result.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--run-validation',action='store_true');group.add_argument('--verify',action='store_true')
    return result


def verify():
    current=state(inside(DEV))
    if current=='partial':raise FileExistsError('Partial validation is not prepared-only success')
    return verify_real() if current=='complete' else verify_prepared()


if __name__=='__main__':
    args=parser().parse_args();value=prepare() if args.prepare else run_validation() if args.run_validation else verify()
    print(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
