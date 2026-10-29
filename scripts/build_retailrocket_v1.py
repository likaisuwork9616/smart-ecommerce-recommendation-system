"""Prepare, build once, independently reconcile every Retailrocket v1 output cell."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import retailrocket_builder as builder

PRIVATE='shop-mysql-runtime/retailrocket_dataset_v1'
VERIFY='shop-mysql-runtime/verification/retailrocket-build-v1'
SPEC='reports/stage8/retailrocket_build_v1_specification.json'
RESULT='reports/stage8/retailrocket_build_v1.json'
ACCEPT='reports/stage8/retailrocket_build_v1_acceptance.json'
POLICY='docs/contracts/retailrocket_recommendation_v1.json'
CODE=['scripts/retailrocket_builder.py','scripts/retailrocket_reference.py','scripts/build_retailrocket_v1.py','tests/test_retailrocket_builder.py']


def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))


def inside(path):
    target=(ROOT/path).resolve()
    if not target.is_relative_to(ROOT):raise ValueError('Path must stay inside shop')
    return target


def descriptor(path):
    p=inside(path);h=hashlib.sha256()
    with p.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':h.hexdigest()}


def check_sources(records):
    for record in records:
        if descriptor(record['path'])!=record:raise ValueError('Frozen source drift: '+record['path'])


def write_new(path,value):
    p=inside(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')


def sources():
    old=read('shop-mysql-runtime/retailrocket_contract_v1/input_guard.json')
    check_sources([*old['sources'],old['acceptance']])
    by_path={s['path']:s for s in [*old['sources'],old['acceptance']]}
    for path in [*CODE,'shop-mysql-runtime/retailrocket_contract_v1/input_guard.json','shop-mysql-runtime/retailrocket_intake_v1/output_guard.json']:
        by_path[path]=descriptor(path)
    return [by_path[p] for p in sorted(by_path)]


def prepare():
    if (ROOT/SPEC).exists():
        guard=read(VERIFY+'/prepared_guard.json');check_sources([guard['specification'],guard['tests'],*guard['sources']])
        return {'status':'prepared_sources_verified','tests_rerun':False}
    if any((ROOT/p).exists() for p in (PRIVATE,RESULT,ACCEPT)):
        raise FileExistsError('Existing or partial build namespace; preserve evidence, do not replay')
    bound=sources()
    folder=inside(VERIFY);folder.mkdir(parents=True,exist_ok=True)
    if not (folder/'before.json').exists():
        names=subprocess.check_output(['git','ls-files','-co','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
        baseline={p:descriptor(p)['sha256'] for p in names if p and p not in CODE and (ROOT/p).is_file()}
        write_new(VERIFY+'/before.json',baseline)
    log=io.StringIO();started=time.perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_retailrocket_builder')
    with contextlib.redirect_stdout(log):outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    elapsed=round(time.perf_counter()-started,6)
    if not outcome.wasSuccessful() or outcome.skipped:print(log.getvalue());raise ValueError('Synthetic acceptance failed')
    with (folder/'tests.log').open('x',encoding='utf-8',newline='\n') as f:f.write(log.getvalue())
    check_sources(bound)
    spec={'status':'prepared_before_real_dataset_build','contract':descriptor(POLICY),'sources':bound,
        'schemas':builder.SCHEMAS,'implementation_details':{
            'row_precedence':'malformed -> excluded; otherwise exact content representative over all valid rows; nonrepresentatives duplicate; representatives outside v1 excluded; others canonical',
            'tail':'row accounting only; outside-v1 events never enter baskets, labels, catalog, visitor history or properties-as-features',
            'context_encoding':'basket index within visitor/session; all baskets with same visitor/session and index <= query index, no full prefix duplication',
            'session_end_fields':'last time and total length are audit-only future diagnostics, forbidden as query model features',
            'query_next_fields':'next_view timestamp/role may diagnose later-session or boundary observations; target_items populated only for labelled rows',
            'boundary_ledger':'all query decisions with immature observation or same-session cross-role next view, including applicable warmup rows; flags independent of primary status',
            'visitor_known_fit':'first ANY qualified event strictly before fit cutoff; diagnostic slice only, no cart/transaction model features',
            'activity':'canonical view event count in train window only; fixed slices 0 / 1 / 2-5 / 6+, diagnostic only',
            'train_query_slices':'fit-cutoff and whole-training activity diagnostics are not causal per-query input features',
            'properties':'all four original members scanned; only available/categoryid become version diagnostics with all critical lineage; generic values remain opaque in original ZIP',
            'property_join_scope':'every distinct item in each current view basket; not a full candidate-catalog availability filter or model feature',
            'catalog':'first qualified view time; filter strictly before each query; nonreachable targets stay in labels',
            'unknowns':'CSV empty is null, JSON [] is empty set, 0/1 are explicit booleans; no_observed_continuation is unlabelled, never a negative',
            'independent_path':'raw ZIP pandas vs production stdlib CSV/SQLite; pandas cumulative groups/shift and merge_asof; compare all cells in all 16 CSVs',
            'execution_scope':'data building and acceptance only; no recommendation fit, candidate selection or ranking metric'},
        'synthetic_tests':{'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped),'elapsed_seconds':elapsed}}
    write_new(SPEC,spec)
    write_new(VERIFY+'/prepared_guard.json',{'specification':descriptor(SPEC),'tests':descriptor(VERIFY+'/tests.log'),'sources':bound})
    return {'status':'prepared','sources':len(bound),'tests':outcome.testsRun}


def verify():
    guard=read(PRIVATE+'/output_guard.json')
    check_sources(guard['sources']+guard['outputs'])
    return {'status':'dataset_and_acceptance_bytes_verified','files':len(guard['outputs']),
            'independent_semantic_readback':'completed during first build; not rerun by --verify','model_fits':0,'ranking_metrics':0}


def run():
    if (ROOT/PRIVATE).exists():
        if not (ROOT/PRIVATE/'output_guard.json').exists():raise FileExistsError('Partial dataset preserved; no replay')
        return verify()
    prepare();spec=read(SPEC)
    check_sources(spec['sources']+[descriptor(SPEC)])
    if (ROOT/RESULT).exists() or (ROOT/ACCEPT).exists():raise FileExistsError('Unexpected public build result')
    private=inside(PRIVATE);private.mkdir()
    started=time.perf_counter()
    try:
        policy=read(POLICY);audit=read('reports/stage8/retailrocket_source_audit_v1.json')
        summary=builder.build(inside(policy['source']['zip_path']),policy,audit,private)
        built_elapsed=round(time.perf_counter()-started,6)
        print(json.dumps({'status':'primary_dataset_written','seconds':built_elapsed,'files':summary['files']}),flush=True)
        from scripts import retailrocket_reference as reference
        accepted=reference.verify(inside(policy['source']['zip_path']),policy,audit,private,builder.SCHEMAS)
        if accepted['roles']!=summary['roles']:raise ValueError('Independent aggregate role mismatch')
        if any(accepted['files'][name]['rows']!=n for name,n in summary['files'].items()):raise ValueError('Independent file counts differ')
        if sum(summary['row_decisions'].values())!=audit['events']['rows']:raise ValueError('Source accounting mismatch')
        if summary['row_decisions'].get('duplicate',0)!=audit['events']['exact_duplicate_excess']:raise ValueError('Duplicate accounting mismatch')
        check_sources(spec['sources'])
        outputs=[dict(descriptor(PRIVATE+'/'+name),rows=summary['files'][name],columns=len(builder.SCHEMAS[name])) for name in builder.SCHEMAS]
        db_record=descriptor(PRIVATE+'/builder.sqlite')
        manifest={'status':'dataset_independently_accepted','contract':descriptor(POLICY),'files':outputs,'inventory':db_record,'scope':summary['scope']}
        write_new(PRIVATE+'/manifest.json',manifest)
        result={'status':'dataset_v1_built_and_independently_accepted','specification':descriptor(SPEC),
                'summary':summary,'files':outputs,'verification':{'independent_rows':accepted['rows'],'independent_cells':accepted['cells'],
                'all_16_csvs_full_readback_passed':True,'aggregate_roles_equal':True,'primary_seconds':built_elapsed,
                'total_seconds':round(time.perf_counter()-started,6)},'scope':summary['scope'],'limitations':summary['limitations']}
        write_new(RESULT,result)
        write_new(ACCEPT,dict(accepted,specification=descriptor(SPEC),result=descriptor(RESULT),synthetic_tests=spec['synthetic_tests'],scope=summary['scope']))
        bound=spec['sources']+[descriptor(SPEC),descriptor(VERIFY+'/prepared_guard.json'),descriptor(VERIFY+'/tests.log')]
        frozen_outputs=[{k:r[k] for k in ('path','bytes','sha256')} for r in outputs]+[db_record,descriptor(PRIVATE+'/manifest.json'),descriptor(RESULT),descriptor(ACCEPT)]
        write_new(PRIVATE+'/output_guard.json',{'sources':bound,'outputs':frozen_outputs})
        return {'status':result['status'],'summary':summary,'verification':result['verification']}
    except Exception as error:
        if not (private/'failure.json').exists():write_new(PRIVATE+'/failure.json',{'status':'failed_partial_preserved','error':str(error),'elapsed_seconds':round(time.perf_counter()-started,6)})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--run',action='store_true');group.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    print(json.dumps(prepare() if args.prepare else run() if args.run else verify(),ensure_ascii=False,indent=2))
