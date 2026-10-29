"""Prepare P0 development entry; execution is validation-only and never opens test."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import retailrocket_popularity_io as adapters
from scripts import retailrocket_popularity_oracle as oracle

POLICY='docs/contracts/retailrocket_popularity_execution_v1.json'
PARENT='docs/contracts/retailrocket_recommendation_v1.json'
UPSTREAM='shop-mysql-runtime/retailrocket_popularity_spec_v1/output_guard.json'
VERIFY='shop-mysql-runtime/verification/retailrocket-popularity-implementation-v1'
PRIVATE='shop-mysql-runtime/retailrocket_popularity_implementation_v1'
DEV='shop-mysql-runtime/retailrocket_popularity_v1/development'
SPEC='reports/stage9/retailrocket_popularity_v1_development_specification.json'
ACCEPT='reports/stage9/retailrocket_popularity_v1_implementation_acceptance.json'
REAL_RESULT='reports/stage9/retailrocket_popularity_v1_development.json'
REAL_ACCEPT='reports/stage9/retailrocket_popularity_v1_development_acceptance.json'
DOC='docs/STAGE9_RETAILROCKET_POPULARITY_IMPLEMENTATION_V1.md'
CODE=['scripts/retailrocket_popularity.py','scripts/retailrocket_popularity_io.py','scripts/retailrocket_popularity_oracle.py',
      'scripts/run_retailrocket_popularity_v1.py','tests/test_retailrocket_popularity.py','tests/test_retailrocket_popularity_entry.py']


def within(root,relative):
    p=(root/relative).resolve()
    if not p.is_relative_to(root):raise ValueError('All artifacts must resolve inside shop')
    return p


def descriptor(root,relative):
    p=within(root,relative);h=hashlib.sha256()
    with p.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return {'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':h.hexdigest()}


def check(root,records):
    for record in records:
        if descriptor(root,record['path'])!=record:raise ValueError('Bound source/output changed: '+record['path'])


def read(path):return json.loads(within(ROOT,path).read_text(encoding='utf-8'))


def write_new(root,relative,value):
    p=within(root,relative);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def state(folder):
    if not folder.exists():return 'absent'
    return 'complete' if (folder/'output_guard.json').is_file() else 'partial'


def require_locked(initial_gate,execution_root):
    if initial_gate['status']!='locked_at_specification_freeze' or initial_gate['test_ranking_started'] is not False or initial_gate['logical_tests_consumed']!=0:
        raise ValueError('Reserved-test gate is not locked')
    for name in ('reserved_test','final_refit','test_usage.jsonl'):
        if (execution_root/name).exists():raise ValueError('Later-phase evidence exists; development cannot restart')


def parser():
    result=argparse.ArgumentParser(description=__doc__)
    group=result.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--run-development',action='store_true');group.add_argument('--verify',action='store_true')
    return result


def sources():
    old=read(UPSTREAM);bound={}
    for r in old['sources']+old['outputs']:
        if r['path'] in bound and r!=bound[r['path']]:raise ValueError('Conflicting source descriptors')
        bound[r['path']]=r
    check(ROOT,list(bound.values()))
    for path in [UPSTREAM,*CODE,DOC,'.venv/pyvenv.cfg',Path(sys.executable).resolve().relative_to(ROOT).as_posix()]:bound[path]=descriptor(ROOT,path)
    return [bound[k] for k in sorted(bound)]


def initial_gate():return read('shop-mysql-runtime/retailrocket_popularity_spec_v1/initial_test_gate.json')


def prepare():
    if state(ROOT/PRIVATE)=='complete':return verify_prepared()
    if state(ROOT/PRIVATE)=='partial' or any((ROOT/p).exists() for p in (SPEC,ACCEPT,DEV,REAL_RESULT,REAL_ACCEPT,VERIFY+'/tests.log')):
        raise FileExistsError('Existing or partial preparation/execution preserved; no overwrite')
    require_locked(initial_gate(),ROOT/'shop-mysql-runtime/retailrocket_popularity_v1')
    bound=sources();started=time.perf_counter();log=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_retailrocket_popularity','tests.test_retailrocket_popularity_entry'])
    with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    if not outcome.wasSuccessful() or outcome.skipped:print(log.getvalue());raise ValueError('Synthetic tests failed; entry not prepared')
    elapsed=round(time.perf_counter()-started,6)
    from tests.test_retailrocket_popularity import fixture,SCHEMAS,PARENT as parent
    synthetic=[]
    for name,many in [('hand_complete_target_and_zero_fallback',False),('universal_positive_order_equivalence',True)]:
        scratch,source,output,policy=fixture(base=ROOT/VERIFY/'acceptance',many=many)
        primary=adapters.build_development(output,source,SCHEMAS,policy,parent)
        accepted=oracle.verify(output,source,SCHEMAS,policy,parent)
        oracle.close(primary['aggregate'],accepted['aggregate'])
        files=[descriptor(ROOT,p.relative_to(ROOT).as_posix()) for p in sorted(scratch.rglob('*')) if p.is_file()]
        synthetic.append({'case':name,'dataset_kind':'synthetic','validation_queries':accepted['aggregate']['queries'],
            'independent_readback_rows':accepted['rows'],'independent_readback_cells':accepted['cells'],
            'ranking_oracle':accepted['ranking_oracle'],'files':files,
            'fit_counters':{'synthetic_primary_fits':1,'synthetic_independent_count_audits':1,'real_primary_fits':0}})
    check(ROOT,bound)
    scope={'synthetic_only':True,'real_primary_fits':0,'real_independent_count_audits':0,'real_ranked_queries':0,
           'real_metric_calculations':0,'real_data_CSV_rows_parsed':0,'reserved_test_enabled':False,'reserved_test_state':'locked',
           'real_development_executed':False,'final_refit_implemented':False,'reserved_test_entry_implemented':False}
    within(ROOT,PRIVATE).mkdir();within(ROOT,VERIFY).mkdir(parents=True,exist_ok=True)
    with within(ROOT,VERIFY+'/tests.log').open('x',encoding='utf-8',newline='\n') as f:f.write(log.getvalue())
    gate={'status':'locked_at_development_entry_freeze','parent_initial_gate':descriptor(ROOT,'shop-mysql-runtime/retailrocket_popularity_spec_v1/initial_test_gate.json'),
          'test_ranking_started':False,'logical_tests_consumed':0,'available_real_operation':'run-development validation only; no final-refit or reserved-test command'}
    write_new(ROOT,PRIVATE+'/test_gate_snapshot.json',gate)
    spec={'status':'real_development_entry_prepared_not_executed','date_asia_taipei':'2026-10-28','sources':bound,'protocol':descriptor(ROOT,POLICY),
        'environment':{'python_version':platform.python_version(),'python_executable':Path(sys.executable).resolve().relative_to(ROOT).as_posix(),
                       'libraries':'stdlib only; independent SQLite/Fraction/Decimal oracle, no new package installation'},
        'schemas':adapters.HEADERS,'allowed_cli_operation':'--run-development after prepared byte guards; validation only',
        'planned_execution':{'primary_fit_limit':1,'independent_count_audits':1,'validation_queries':166897,'validation_visitors':62235,
             'query_input':'accepted queries.csv exact validation role; sorted unique query keys','output_namespace':DEV,
             'model_identity':'SHA256 of canonical algorithm/window/role/sorted positive counts; dataset/code/environment identity separately bound in input/output manifests',
             'ranker_isolation':'frozen counts/query clock/causal catalog only; no target or query diagnostics',
             'exact_optimization':'production positive-count order plus zero-count order filtered per query; oracle either full sort or proves all positive fit IDs precede every validation query and >=10 positives',
             'metric_oracle':'50-digit Decimal logarithms plus exact Fraction recall/MRR, all rows compared; scalar floats abs/rel tolerance 1e-12',
             'failure':'source/hash/schema/identity/denominator/finite-value mismatch stops; preserve partial evidence and refuse replay',
             'scope':'fit train once, validation rank only, independent full readback; no training ranking, final refit or test operation'},
        'synthetic_tests':{'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped),'elapsed_seconds':elapsed},
        'scope':scope,'test_gate_snapshot':descriptor(ROOT,PRIVATE+'/test_gate_snapshot.json')}
    write_new(ROOT,SPEC,spec)
    acceptance={'status':'P0_evaluator_synthetic_hand_oracle_acceptance_passed_development_entry_frozen','specification':descriptor(ROOT,SPEC),
        'sources_verified':len(bound),'tests':spec['synthetic_tests'],'synthetic_cases':synthetic,
        'synthetic_readback':{'rows':sum(c['independent_readback_rows'] for c in synthetic),'cells':sum(c['independent_readback_cells'] for c in synthetic)},
        'scope':scope,'next_step':'explicitly execute one guarded development fit and full validation only; reserved test remains locked'}
    write_new(ROOT,ACCEPT,acceptance)
    outputs=[descriptor(ROOT,p) for p in (SPEC,ACCEPT,PRIVATE+'/test_gate_snapshot.json',VERIFY+'/tests.log')]
    for c in synthetic:outputs.extend(c['files'])
    write_new(ROOT,PRIVATE+'/output_guard.json',{'sources':bound,'outputs':outputs})
    return {'status':acceptance['status'],'sources':len(bound),'tests':outcome.testsRun,'synthetic_readback':acceptance['synthetic_readback'],'scope':scope}


def verify_prepared():
    guard=read(PRIVATE+'/output_guard.json');check(ROOT,guard['sources']+guard['outputs'])
    return {'status':'prepared_implementation_sources_and_synthetic_evidence_verified','sources':len(guard['sources']),
            'scope_at_prepare':read(ACCEPT)['scope'],'real_data_CSVs_parsed':False,'fits_or_metrics_recomputed':False}


def verify_development():
    guard=read(DEV+'/output_guard.json');check(ROOT,guard['sources']+guard['outputs'])
    return {'status':'existing_development_sources_and_outputs_verified','fits_rerun':False,'metrics_recomputed':False,'reserved_test_executed_by_this_command':False}


def verify():
    current=state(ROOT/DEV)
    if current=='partial':raise FileExistsError('Partial development must not be reported as prepared-only success')
    return verify_development() if current=='complete' else verify_prepared()


def run_development():
    current=state(ROOT/DEV)
    if current=='complete':return verify_development()
    if current=='partial':raise FileExistsError('Partial development preserved; no replay')
    if state(ROOT/PRIVATE)!='complete':raise ValueError('Prepare implementation acceptance before any real fit')
    verify_prepared();require_locked(initial_gate(),ROOT/'shop-mysql-runtime/retailrocket_popularity_v1')
    if any((ROOT/p).exists() for p in (REAL_RESULT,REAL_ACCEPT)):raise FileExistsError('Existing public development evidence')
    spec=read(SPEC);policy=read(POLICY);parent=read(PARENT);schemas=read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
    source=ROOT/'shop-mysql-runtime/retailrocket_dataset_v1';folder=within(ROOT,DEV);folder.mkdir(parents=True)
    write_new(ROOT,DEV+'/started.json',{'operation':'single_primary_development_fit_then_validation','primary_fit_attempts':1,
             'prepared_specification':descriptor(ROOT,SPEC),'test_gate':'locked','note':'marker written before fit; partial failures cannot silently rerun'})
    started=time.perf_counter()
    try:
        primary=adapters.build_development(folder,source,schemas,policy,parent)
        accepted=oracle.verify(folder,source,schemas,policy,parent);oracle.close(primary['aggregate'],accepted['aggregate'])
        check(ROOT,spec['sources']);require_locked(initial_gate(),ROOT/'shop-mysql-runtime/retailrocket_popularity_v1')
        files=[descriptor(ROOT,(folder/name).relative_to(ROOT).as_posix()) for name in [*adapters.HEADERS,'fit_audit.json','aggregate.json']]
        result={'status':'development_fit_and_full_validation_independently_accepted','specification':descriptor(ROOT,SPEC),
                'scope':{'real_primary_fits':1,'real_independent_count_audits':1,'validation_ranked_queries':primary['aggregate']['queries'],
                         'training_ranked_queries':0,'reserved_test_ranked_queries':0,'final_refits':0,'reserved_test_state':'locked'},
                'fit_audit':primary['fit_audit'],'validation':primary['aggregate'],'files':files,
                'verification':{'rows':accepted['rows'],'cells':accepted['cells'],'ranking_oracle':accepted['ranking_oracle'],
                                'elapsed_seconds':round(time.perf_counter()-started,6)}}
        write_new(ROOT,REAL_RESULT,result)
        write_new(ROOT,REAL_ACCEPT,{'status':'all_validation_output_cells_and_aggregates_independently_accepted','result':descriptor(ROOT,REAL_RESULT),
                                   'files':accepted['files'],'scope':result['scope'],'oracle':'separate SQL counts, exact rank proof and Decimal/Fraction metrics'})
        write_new(ROOT,DEV+'/manifest.json',{'status':'development_accepted','fit_id':primary['fit_audit']['fit_id'],'files':files,
                                           'prepared_specification':descriptor(ROOT,SPEC),'scope':result['scope']})
        frozen_inputs=spec['sources']+[descriptor(ROOT,p) for p in (SPEC,ACCEPT,PRIVATE+'/output_guard.json')]
        frozen_outputs=files+[descriptor(ROOT,p) for p in (REAL_RESULT,REAL_ACCEPT,DEV+'/manifest.json',DEV+'/started.json')]
        write_new(ROOT,DEV+'/output_guard.json',{'sources':frozen_inputs,'outputs':frozen_outputs})
        return {'status':result['status'],'scope':result['scope'],'validation':result['validation']}
    except Exception as error:
        write_new(ROOT,DEV+'/failure.json',{'status':'partial_development_preserved','error':str(error),'primary_fit_attempts':1,'reserved_test':'locked'})
        raise


if __name__=='__main__':
    args=parser().parse_args()
    result=prepare() if args.prepare else run_development() if args.run_development else verify()
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
