"""K1 synthetic acceptance then train-only cost. No real validation/final/test CLI."""
import argparse
import contextlib
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts import freeze_retailrocket_session_knn_v1 as frozen
from scripts import retailrocket_session_knn_cost as cost
from scripts import retailrocket_session_knn_oracle as oracle
from scripts import retailrocket_popularity_io as clock_io

PRIVATE = 'shop-mysql-runtime/retailrocket_session_knn_implementation_v1'
VERIFY = 'shop-mysql-runtime/verification/retailrocket-session-knn-implementation-v1'
REPORT = 'reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json'
MANIFEST = 'reports/stage12/retailrocket_session_knn_v1_implementation_specification.json'
DOC = 'docs/STAGE12_RETAILROCKET_KNN_IMPLEMENTATION_V1.md'
CONTRACT = 'docs/contracts/retailrocket_session_knn_implementation_v1.json'
NEW = [CONTRACT,DOC,'scripts/retailrocket_session_knn.py','scripts/retailrocket_session_knn_evaluation.py',
       'scripts/retailrocket_session_knn_oracle.py','scripts/retailrocket_session_knn_cost.py',
       'scripts/prepare_retailrocket_session_knn_v1.py','tests/test_retailrocket_session_knn.py',
       'tests/test_retailrocket_session_knn_entry.py']
LIMITS = {'maximum_process_RSS_bytes':8*1024**3,'maximum_execution_disk_bytes':20*1024**3,
          'minimum_free_disk_bytes':8*1024**3,'minimum_available_memory_bytes':4*1024**3,
          'maximum_elapsed_seconds':21600,'monitor_interval_seconds':0.5}


def read(name): return frozen.read(ROOT,name)
def descriptor(name): return frozen.describe(ROOT,name)
def inside(name): return frozen.path(ROOT,name)
def write(name,value): return frozen.write_new(ROOT,name,value)


def state(root):
    root = Path(root)
    if not root.exists(): return 'absent'
    if (root/'output_guard.json').exists() and not (root/'failure.json').exists(): return 'complete'
    return 'partial'


def validate_policy(policy,implementation):
    if policy['resources']['limits'] != LIMITS:
        raise ValueError('Frozen resource limits differ')
    if (implementation['protocol_id'] != 'retailrocket_session_knn_implementation_v1'
            or implementation['parent_protocol'] != frozen.POLICY
            or implementation['allowed_commands'] != ['--prepare','--verify']
            or implementation['real_validation_enabled'] is not False
            or implementation['real_K1_index_build_enabled'] is not False
            or implementation['final_refit_enabled'] is not False or implementation['reserved_test_enabled'] is not False):
        raise ValueError('Preparation scope differs')


def validate_measurements(values):
    for field,limit in [('RSS','maximum_process_RSS_bytes'),('disk','maximum_execution_disk_bytes'),('elapsed','maximum_elapsed_seconds')]:
        if values[field] > LIMITS[limit]: raise RuntimeError(field+' limit exceeded')
    for field,limit in [('free_disk','minimum_free_disk_bytes'),('available_memory','minimum_available_memory_bytes')]:
        if values[field] < LIMITS[limit]: raise RuntimeError(field+' below floor')


class Budget:
    def __init__(self,folder):
        self.folder=Path(folder);self.start=time.monotonic();self.last=-float('inf')
        self.peak=0;self.disk_peak=0;self.samples=0
    def __call__(self,force=False):
        now=time.monotonic()
        if not force and now-self.last < LIMITS['monitor_interval_seconds']: return
        self.last=now
        values={'RSS':psutil.Process().memory_info().rss,
                'disk':sum(p.stat().st_size for p in self.folder.rglob('*') if p.is_file()),
                'free_disk':shutil.disk_usage(self.folder).free,'available_memory':psutil.virtual_memory().available,
                'elapsed':now-self.start}
        validate_measurements(values)
        self.peak=max(self.peak,values['RSS']);self.disk_peak=max(self.disk_peak,values['disk']);self.samples+=1
    def receipt(self):
        self(force=True)
        return {'elapsed_seconds':round(time.monotonic()-self.start,6),'observed_peak_sampled_RSS_bytes':self.peak,
                'observed_peak_execution_disk_bytes':self.disk_peak,'samples':self.samples,'limits':LIMITS,
                'enforcement':'Cooperative 0.5s checks during cost rows/SQL and phase boundaries; no OS instantaneous hard-limit claim.'}


def source_snapshot():
    prior=read(frozen.REPORT)
    bound={d['path']:d for d in prior['sources']}
    names=NEW+[frozen.REPORT,frozen.PRIVATE+'/output_guard.json']
    for name in names:
        current=descriptor(name)
        if name in bound and bound[name]!=current: raise ValueError('Changed frozen dependency')
        bound[name]=current
    for item in bound.values(): frozen.check(ROOT,item)
    return [bound[name] for name in sorted(bound)]


def verify():
    if state(inside(PRIVATE))!='complete': raise ValueError('No complete preparation; preserve partial evidence')
    guard=read(PRIVATE+'/output_guard.json')
    for item in guard['sources']+guard['outputs']: frozen.check(ROOT,item)
    frozen.locked(ROOT,at_freeze=True)
    validate_policy(read(frozen.POLICY),read(CONTRACT))
    expected={'started.json','test_gate_snapshot.json','output_guard.json'}
    if {p.name for p in inside(PRIVATE).iterdir()}!=expected: raise ValueError('Preparation namespace changed')
    return {'status':'K1_implementation_synthetic_and_train_cost_bytes_verified',
            'sources_verified':len(guard['sources']),'outputs_verified':len(guard['outputs']),
            'research_recomputed':False,'real_validation_ranked_queries':0,'reserved_test':'locked'}


def prepare():
    current=state(inside(PRIVATE))
    if current=='complete': return verify()
    if current!='absent' or any(inside(name).exists() for name in (REPORT,MANIFEST,VERIFY+'/train_cost',VERIFY+'/tests.log',VERIFY+'/acceptance')):
        raise FileExistsError('Partial/pre-existing preparation preserved; no retry or overwrite')
    frozen.verify();frozen.locked(ROOT,at_freeze=True)
    policy=read(frozen.POLICY);implementation=read(CONTRACT);validate_policy(policy,implementation)
    initial=source_snapshot()
    if np.__version__ != policy['uncertainty']['numpy_version']:
        raise ValueError('Frozen NumPy version differs')
    inside(VERIFY).mkdir(parents=True,exist_ok=True)
    write(PRIVATE+'/started.json',{'operation':'K1_synthetic_then_train_cost','real_validation_enabled':False})
    started=time.monotonic();budget=Budget(inside(VERIFY))
    try:
        budget(force=True);log=io.StringIO()
        suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_retailrocket_session_knn',
            'tests.test_retailrocket_session_knn_entry','tests.test_retailrocket_session_knn_spec'])
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        with inside(VERIFY+'/tests.log').open('x',encoding='utf-8',newline='\n') as stream: stream.write(log.getvalue())
        if not outcome.wasSuccessful() or outcome.skipped: raise ValueError('Synthetic/guard tests failed')
        from tests.test_retailrocket_session_knn import run_case
        cases=[]
        for boundary in (False,True):
            budget(force=True)
            target,_=run_case(inside(VERIFY+'/acceptance'),boundary)
            checked=oracle.verify_case(target,persist=True)
            files=[descriptor(p.relative_to(ROOT).as_posix()) for p in sorted(target.rglob('*')) if p.is_file()]
            cases.append({'name':'501_neighbor_boundary' if boundary else 'hand_cold_crossing_and_four_arms',
                          'kind':'synthetic_only','readback':checked,'files':files})
        budget(force=True)
        # No real item-array decoding before all formal synthetic oracle cases have passed.
        schemas=read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
        start,end=map(clock_io.ms,policy['comparison']['fit_window_utc'])
        cost_start=time.monotonic()
        measured=cost.audit(inside(policy['model']['source']),schemas['baskets.csv'],start,end,
            inside('shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/support.csv'),
            inside('shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/train_sessions.jsonl'),inside(VERIFY+'/train_cost'),budget)
        cost_elapsed=round(time.monotonic()-cost_start,6)
        historical=read('reports/stage10/retailrocket_cooccurrence_v1_implementation_acceptance.json')['train_only_cost']
        for key in ('train_sessions','train_baskets','singleton_sessions','basket_item_memberships','distinct_session_item_memberships'):
            if measured[key]!=historical[key]: raise ValueError('Train population differs from C1: '+key)
        if read(VERIFY+'/train_cost/cost.json')!=measured: raise ValueError('Cost JSON readback differs')
        usage=budget.receipt();write(VERIFY+'/train_cost/resources.json',dict(usage,cost_elapsed_seconds=cost_elapsed))
        for item in initial: frozen.check(ROOT,item)
        frozen.locked(ROOT,at_freeze=True)
        scope={'K1_core_and_four_arm_evaluator_implemented':True,'synthetic_SQL_full_pool_full_catalog_oracle_passed':True,
               'real_K1_index_builds':0,'real_P0_C1_D1_refits_or_rerankings':0,'real_validation_ranked_queries':0,
               'real_validation_metrics':0,'real_bootstrap_replicates':0,'train_only_cost_passes':2,
               'train_item_arrays_decoded_per_pass':measured['train_item_arrays_decoded_per_pass'],
               'real_validation_or_test_item_arrays_decoded':0,'final_refits':0,'reserved_test_ranked_queries':0,
               'reserved_test_state':'locked','real_validation_entry_implemented':False}
        tests={'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped)}
        gate={'state':'locked','K1_test_authorized':False,'real_validation_enabled':False,'logical_test_runs_consumed_this_round':0}
        write(PRIVATE+'/test_gate_snapshot.json',gate)
        manifest={'status':'K1_implementation_frozen_synthetic_and_train_cost_only','date_asia_taipei':'2026-10-29',
                  'protocol':descriptor(frozen.POLICY),'implementation_contract':descriptor(CONTRACT),'sources':initial,
                  'environment':{'python':platform.python_version(),'numpy':np.__version__,'psutil':psutil.__version__},
                  'tests':tests,'limits':LIMITS,'scope':scope,
                  'next_gate':'Separate source-bound real-validation loader/entry and acceptance required; no --run-validation command here.'}
        write(MANIFEST,manifest)
        report={'status':'K1_hand_synthetic_independent_oracle_and_train_cost_accepted',
                'specification':descriptor(MANIFEST),'sources_verified':len(initial),'tests':tests,'synthetic_cases':cases,
                'train_only_cost':measured,'cost_elapsed_seconds':cost_elapsed,'preparation_resources':usage,
                'scope':scope,'elapsed_seconds':round(time.monotonic()-started,6),
                'limits':'Train-only counts do not establish full-query search/oracle speed, real ranking quality, or final model suitability.'}
        write(REPORT,report)
        outputs=[descriptor(name) for name in (REPORT,MANIFEST,PRIVATE+'/started.json',PRIVATE+'/test_gate_snapshot.json',VERIFY+'/tests.log')]
        for case in cases: outputs.extend(case['files'])
        outputs.extend(descriptor(p.relative_to(ROOT).as_posix()) for p in sorted(inside(VERIFY+'/train_cost').rglob('*')) if p.is_file())
        write(PRIVATE+'/output_guard.json',{'sources':initial,'outputs':outputs})
        return {'status':report['status'],'sources_verified':len(initial),'tests':tests,
                'train_only_cost':measured,'cost_elapsed_seconds':cost_elapsed,'scope':scope}
    except Exception as exc:
        write(PRIVATE+'/failure.json',{'state':'failed','error':type(exc).__name__+': '+str(exc)})
        raise


def parser():
    result=argparse.ArgumentParser(description=__doc__)
    group=result.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--verify',action='store_true')
    return result


if __name__=='__main__':
    args=parser().parse_args()
    print(json.dumps(prepare() if args.prepare else verify(),indent=2))
