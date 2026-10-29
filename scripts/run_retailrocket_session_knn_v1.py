"""Prepare/freeze K1 real-validation entry; run only on a later explicit request."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import numpy as np
import psutil
from scripts import prepare_retailrocket_session_knn_v1 as prior
from scripts import freeze_retailrocket_session_knn_v1 as frozen
from scripts import retailrocket_popularity_io as dates
from scripts import retailrocket_session_knn_io as adapter
from scripts import retailrocket_session_knn_readback as oracle

PRIVATE='shop-mysql-runtime/retailrocket_session_knn_validation_entry_v1'
VERIFY='shop-mysql-runtime/verification/retailrocket-session-knn-validation-entry-v1'
DEV=frozen.K1_EXECUTION
CONTRACT='docs/contracts/retailrocket_session_knn_validation_entry_v1.json'
DOC='docs/STAGE12_RETAILROCKET_KNN_VALIDATION_ENTRY_V1.md'
SPEC='reports/stage12/retailrocket_session_knn_v1_validation_entry_specification.json'
ACCEPT='reports/stage12/retailrocket_session_knn_v1_validation_entry_acceptance.json'
RESULT='reports/stage12/retailrocket_session_knn_v1_validation.json'
REAL_ACCEPT='reports/stage12/retailrocket_session_knn_v1_validation_acceptance.json'
NEW=[CONTRACT,DOC,'scripts/retailrocket_session_knn_io.py','scripts/retailrocket_session_knn_readback.py',
     'scripts/run_retailrocket_session_knn_v1.py','tests/test_retailrocket_session_knn_validation.py',
     'tests/test_retailrocket_session_knn_validation_entry.py']
DIRECTORIES={'dataset':'shop-mysql-runtime/retailrocket_dataset_v1',
    'P0':'shop-mysql-runtime/retailrocket_popularity_v1/development',
    'C1':'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1',
    'D1':'shop-mysql-runtime/retailrocket_directed_paired_v1'}
INPUTS={'dataset':('baskets.csv','queries.csv','catalog.csv'),
    'P0':('item_counts.csv','ranked_queries.csv','query_metrics.csv','query_slices.csv','fit_audit.json'),
    'C1':('support.csv','train_sessions.jsonl','queries.jsonl','bootstrap.jsonl','fit_audit.json'),
    'D1':('queries.jsonl','fit_audit.json')}
state=prior.state


class Budget(prior.Budget):
    def receipt(self):
        result=super().receipt()
        result['enforcement']='Cooperative checks during hashing, rows, fit, output, query, full oracle loops, bootstrap and SQLite VM; sampled, not OS-hard.'
        return result


@contextlib.contextmanager
def synthetic_only_reads():
    """During preparation, forbid semantic opens of all direct real row sources."""
    protected={inside(directory+'/'+name).resolve() for directory in DIRECTORIES.values()
               for names in INPUTS.values() for name in names if name.endswith(('.csv','.jsonl'))}
    original=Path.open
    def guarded(path,mode='r',*args,**kwargs):
        if 'b' not in mode and path.resolve() in protected:
            raise PermissionError('Preparation cannot decode real data/control rows: '+str(path))
        return original(path,mode,*args,**kwargs)
    with patch.object(Path,'open',guarded): yield


def inside(name): return frozen.path(ROOT,name)
def read(name): return frozen.read(ROOT,name)
def write(name,value): return frozen.write_new(ROOT,name,value)
def descriptor(name): return frozen.describe(ROOT,name)


def check(records,watch=lambda:None):
    for record in records:
        target=inside(record['path']); h=hashlib.sha256()
        with target.open('rb') as stream:
            while block:=stream.read(1024*1024): watch();h.update(block)
        if target.stat().st_size!=record['bytes'] or h.hexdigest()!=record['sha256']:
            raise ValueError('Frozen source/output changed: '+record['path'])


def environment():
    return {'python':platform.python_version(),'numpy':np.__version__,'psutil':psutil.__version__,
            'implementation':platform.python_implementation(),'byteorder':sys.byteorder}


def gates(preparing=False):
    frozen.locked(ROOT,at_freeze=preparing)
    for name in (DEV+'/final_refit',DEV+'/reserved_test',DEV+'/test_usage.jsonl'):
        if inside(name).exists(): raise ValueError('K1 final/test namespace forbidden')


def validate_contract():
    policy=read(frozen.POLICY); contract=read(CONTRACT)
    required={'protocol_id':'retailrocket_session_knn_validation_entry_v1',
        'parent_protocol':frozen.POLICY,'implementation_protocol':prior.CONTRACT,
        'commands':['--prepare','--verify','--run-validation'],'prepare_runs_real_validation':False,
        'final_selection_enabled':False,'final_refit_enabled':False,'reserved_test_enabled':False,
        'real_execution_requires_later_explicit_request':True,'limits':prior.LIMITS,
        'directories':DIRECTORIES,'artifacts':list(adapter.ARTIFACTS)}
    for field,value in required.items(): oracle.exact(contract[field],value)
    oracle.exact(policy['resources']['limits'],prior.LIMITS)
    if np.__version__!=policy['uncertainty']['numpy_version']: raise ValueError('Frozen NumPy mismatch')


def configuration():
    """Metadata only: no raw CSV/JSONL rows or real model invocation."""
    policy=read(frozen.POLICY); data=read('docs/contracts/retailrocket_recommendation_v1.json')
    d1=read('reports/stage11/retailrocket_directed_v1_validation.json')
    identities=read('docs/contracts/retailrocket_directed_paired_v1.json')['reference_identity']
    cost=read(prior.REPORT)['train_only_cost']
    return {'schemas':read('reports/stage8/retailrocket_build_v1_specification.json')['schemas'],
        'train_window_ms':list(map(dates.ms,policy['comparison']['fit_window_utc'])),
        'validation_window_ms':list(map(dates.ms,policy['comparison']['evaluation_window_utc'])),
        'validation_window_utc':policy['comparison']['evaluation_window_utc'],
        'role_windows_ms':{role:list(map(dates.ms,data['time_roles'][role])) for role in ('warmup','train','validation')},
        'control_fit_ids':{'P0':identities['P0_fit_id'],'C1':identities['C1_fit_id'],'D1':d1['fit_audit']['fit_id']},
        'fixed_validation':policy['fixed_validation'],'expected_controls':d1['validation']['arms'],
        'train_cost_audit':{key:cost[key] for key in ('train_sessions','singleton_sessions','train_baskets',
            'basket_item_memberships','distinct_session_item_memberships','positive_support_items',
            'maximum_session_items','maximum_posting_size')}}


def source_snapshot():
    guard=read(prior.PRIVATE+'/output_guard.json'); bound={}
    for item in guard['sources']+guard['outputs']:
        if item['path'] in bound and bound[item['path']]!=item: raise ValueError('Conflicting source identity')
        bound[item['path']]=item
    for name in NEW+[prior.PRIVATE+'/output_guard.json']:
        current=descriptor(name)
        if name in bound and bound[name]!=current: raise ValueError('Frozen source edited')
        bound[name]=current
    direct=[]
    for arm,names in INPUTS.items():
        for name in names:
            path=DIRECTORIES[arm]+'/'+name
            if path not in bound: raise ValueError('Required input missing inherited binding: '+path)
            direct.append(dict(bound[path],role=arm))
    sources=[bound[name] for name in sorted(bound)];check(sources)
    return sources,direct


def verify_prepared():
    if state(inside(PRIVATE))!='complete': raise ValueError('Entry preparation incomplete')
    guard=read(PRIVATE+'/output_guard.json');check(guard['sources']+guard['outputs'])
    validate_contract();gates()
    spec=read(SPEC)
    oracle.exact(spec['environment'],environment())
    oracle.exact(spec['configuration'],configuration())
    return {'status':'K1_validation_entry_sources_synthetic_acceptance_bytes_verified',
        'sources_verified':len(guard['sources']),'outputs_verified':len(guard['outputs']),
        'research_recomputed':False,'real_validation_executed_by_verify':False,'reserved_test':'locked'}


def verify_run(folder):
    if state(folder)!='complete': raise FileExistsError('Partial execution preserved; no replay')
    guard=json.loads((folder/'output_guard.json').read_text(encoding='utf-8'))
    check(guard['sources']+guard['outputs'])
    expected=set(adapter.ARTIFACTS)|{'started.json','oracle.sqlite','resource_usage.json','acceptance.json','output_guard.json'}
    if {p.name for p in folder.iterdir()}!=expected: raise ValueError('Unexpected execution artifact')
    return {'status':'existing_K1_validation_bytes_verified','research_recomputed':False}


def execute_once(folder,paths,config,sources,gate_check,budget_factory=Budget,publish=None):
    """Same lifecycle for formal synthetic acceptance and the future real entry."""
    current=state(folder)
    if current=='complete': gate_check();return verify_run(folder)
    if current!='absent': raise FileExistsError('Partial K1 execution preserved; no replay')
    gate_check()
    folder.mkdir(parents=True,exist_ok=False)  # Atomic namespace claim, no parallel second run.
    relative=folder.relative_to(ROOT).as_posix()
    write(relative+'/started.json',{'operation':'single_train_index_then_validation_and_full_oracle',
                                  'primary_fit_attempts':1,'reserved_test':'locked'})
    try:
        budget=budget_factory(folder);budget(force=True);check(sources,budget)
        primary=adapter.build(folder,paths,config,budget)
        independent=oracle.verify(folder,paths,config,budget)
        oracle.close(primary['aggregate'],independent['aggregate'])
        oracle.exact(primary['fit_audit'],independent['fit_audit'])
        check(sources,budget);gate_check();usage=budget.receipt()
        write(relative+'/resource_usage.json',usage)
        receipt={k:v for k,v in independent.items() if k!='aggregate'}
        write(relative+'/acceptance.json',receipt)
        outputs=[descriptor(p.relative_to(ROOT).as_posix()) for p in sorted(folder.iterdir()) if p.is_file()]
        if publish is not None: outputs.extend(publish(primary,receipt,usage,outputs))
        check(outputs);gate_check()
        write(relative+'/output_guard.json',{'sources':sources,'outputs':outputs})
        return {'status':'single_K1_validation_and_complete_oracle_accepted','readback':receipt,'resources':usage}
    except BaseException as error:
        write(relative+'/failure.json',{'status':'partial_K1_execution_preserved','error':type(error).__name__+': '+str(error),
              'primary_fit_attempts':1,'reserved_test':'locked','retry_allowed':False})
        raise


def run_validation():
    current=state(inside(DEV))
    if current=='partial': raise FileExistsError('Partial real K1 execution preserved')
    verify_prepared();gates()
    if current=='complete': return verify_run(inside(DEV))
    if any(inside(name).exists() for name in (RESULT,REAL_ACCEPT)): raise FileExistsError('Existing real result preserved')
    spec=read(SPEC);sources=spec['sources']+[descriptor(name) for name in (SPEC,ACCEPT,PRIVATE+'/output_guard.json')]
    def publish(primary,receipt,usage,files):
        scope={'real_K1_primary_index_builds':1,'real_independent_index_audits':1,'control_refits_or_rerankings':0,
               'validation_queries':spec['configuration']['fixed_validation']['queries'],'final_refits':0,
               'reserved_test_ranked_queries':0,'reserved_test':'locked','final_model_selected':False}
        write(RESULT,{'status':'K1_exposed_development_validation_independently_accepted','specification':descriptor(SPEC),
              'scope':scope,**primary,'resources':usage,'files':files})
        write(REAL_ACCEPT,{'result':descriptor(RESULT),'scope':scope,'readback':receipt})
        return [descriptor(RESULT),descriptor(REAL_ACCEPT)]
    return execute_once(inside(DEV),{k:inside(v) for k,v in DIRECTORIES.items()},spec['configuration'],sources,gates,publish=publish)


def prepare():
    current=state(inside(PRIVATE))
    if current=='complete': return verify_prepared()
    if current!='absent' or any(inside(p).exists() for p in (SPEC,ACCEPT,VERIFY+'/tests.log',VERIFY+'/acceptance')):
        raise FileExistsError('Partial/existing entry preparation preserved')
    gates(preparing=True);validate_contract();prior.verify()
    sources,direct=source_snapshot();config=configuration()
    inside(VERIFY).mkdir(parents=True,exist_ok=True)
    write(PRIVATE+'/started.json',{'operation':'synthetic_source_loader_entry_freeze','real_validation_enabled_this_round':False})
    try:
        log=io.StringIO()
        suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_retailrocket_session_knn_validation',
            'tests.test_retailrocket_session_knn_validation_entry','tests.test_retailrocket_session_knn',
            'tests.test_retailrocket_session_knn_entry','tests.test_retailrocket_session_knn_spec'])
        with synthetic_only_reads(),contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        with inside(VERIFY+'/tests.log').open('x',encoding='utf-8',newline='\n') as stream:stream.write(log.getvalue())
        if not outcome.wasSuccessful() or outcome.skipped: raise ValueError('Synthetic acceptance tests failed')
        from tests.test_retailrocket_session_knn_validation import run_case
        cases=[]
        for boundary in (False,True):
            with synthetic_only_reads():
                target,result=run_case(inside(VERIFY+'/acceptance'),boundary)
            files=[descriptor(p.relative_to(ROOT).as_posix()) for p in sorted(target.rglob('*')) if p.is_file()]
            cases.append({'case':'501_boundary' if boundary else 'cross_role_cold_and_four_arms',
                          'kind':'synthetic_source_files_through_single_run_entry','readback':result['readback'],'files':files})
        check(sources);gates(preparing=True)
        tests={'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped)}
        scope={'real_source_CSV_or_JSONL_rows_parsed':0,'real_K1_index_builds':0,'real_validation_ranked_queries':0,
               'real_validation_metric_runs':0,'real_bootstrap_replicates':0,'train_cost_recomputed':False,
               'final_model_selected':False,'final_refits':0,'reserved_test_ranked_queries':0,'reserved_test':'locked'}
        write(PRIVATE+'/locked_scope.json',dict(scope,reference_gates=[descriptor(p) for p in frozen.prior.GATES]))
        write(SPEC,{'status':'K1_validation_loader_full_readback_single_entry_frozen_without_real_run',
              'sources':sources,'direct_input_bindings':direct,'configuration':config,'environment':environment(),
              'limits':prior.LIMITS,'tests':tests,'scope':scope,'artifacts':list(adapter.ARTIFACTS),
              'execution_command':'--run-validation; requires a later explicit task, not executed by --prepare or --verify'})
        write(ACCEPT,{'status':'K1_validation_entry_synthetic_and_source_binding_accepted','specification':descriptor(SPEC),
              'sources_verified':len(sources),'direct_inputs_bound':len(direct),'tests':tests,'synthetic_cases':cases,'scope':scope})
        outputs=[descriptor(p) for p in (SPEC,ACCEPT,PRIVATE+'/started.json',PRIVATE+'/locked_scope.json',VERIFY+'/tests.log')]
        for case in cases: outputs.extend(case['files'])
        check(outputs);write(PRIVATE+'/output_guard.json',{'sources':sources,'outputs':outputs})
        return {'status':'K1_validation_entry_frozen_no_real_validation','sources_verified':len(sources),
                'direct_inputs_bound':len(direct),'tests':tests,'scope':scope}
    except BaseException as error:
        write(PRIVATE+'/failure.json',{'status':'partial_preparation_preserved','error':type(error).__name__+': '+str(error)})
        raise


def verify():
    if state(inside(DEV))=='partial': raise FileExistsError('Partial execution is not preparation success')
    prepared=verify_prepared()
    return verify_run(inside(DEV)) if state(inside(DEV))=='complete' else prepared


def parser():
    result=argparse.ArgumentParser(description=__doc__);group=result.add_mutually_exclusive_group(required=True)
    for flag in ('--prepare','--verify','--run-validation'): group.add_argument(flag,action='store_true')
    return result


if __name__=='__main__':
    args=parser().parse_args()
    print(json.dumps(prepare() if args.prepare else run_validation() if args.run_validation else verify(),indent=2))
