"""Freeze P0/evaluator execution specification; never fit, rank or parse data CSVs."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.retailrocket_popularity_protocol import validate

POLICY='docs/contracts/retailrocket_popularity_execution_v1.json'
DOC='docs/STAGE9_RETAILROCKET_POPULARITY_SPEC_V1.md'
PRIVATE='shop-mysql-runtime/retailrocket_popularity_spec_v1'
VERIFY='shop-mysql-runtime/verification/retailrocket-popularity-spec-v1'
SPEC='reports/stage9/retailrocket_popularity_v1_specification.json'
ACCEPT='reports/stage9/retailrocket_popularity_v1_spec_acceptance.json'
NEW_SOURCES=[POLICY,DOC,'scripts/retailrocket_popularity_protocol.py','scripts/freeze_retailrocket_popularity_v1.py','tests/test_retailrocket_popularity_protocol.py','requirements-lock.txt']


def within(root,relative):
    p=(root/relative).resolve()
    if not p.is_relative_to(root):raise ValueError('Path must resolve inside shop')
    return p


def descriptor(root,relative):
    p=within(root,relative);h=hashlib.sha256()
    with p.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return {'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':h.hexdigest()}


def read(relative):return json.loads(within(ROOT,relative).read_text(encoding='utf-8'))


def check(records):
    for record in records:
        if descriptor(ROOT,record['path'])!=record:raise ValueError('Frozen source mismatch: '+record['path'])


def write_new(relative,value):
    path=within(ROOT,relative);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')


def collect_sources():
    data_guard_path='shop-mysql-runtime/retailrocket_dataset_v1/output_guard.json'
    data=read(data_guard_path);bound={}
    for r in data['sources']+data['outputs']:
        if r['path'] in bound and r!=bound[r['path']]:raise ValueError('Inconsistent source descriptors')
        bound[r['path']]=r
    check(list(bound.values()))
    for relative in [data_guard_path,*NEW_SOURCES]:bound[relative]=descriptor(ROOT,relative)
    return [bound[p] for p in sorted(bound)]


def freeze():
    if (ROOT/PRIVATE).exists():
        if not (ROOT/PRIVATE/'output_guard.json').exists():raise FileExistsError('Partial freeze namespace preserved; no replay')
        return verify()
    if any((ROOT/p).exists() for p in (SPEC,ACCEPT,VERIFY+'/tests.log')):raise FileExistsError('Existing freeze evidence; preserve, do not overwrite')
    started=time.perf_counter()
    policy=read(POLICY);parent=read('docs/contracts/retailrocket_recommendation_v1.json');build=read('reports/stage8/retailrocket_build_v1.json')
    checks=validate(policy,parent,build)
    bound=collect_sources()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_retailrocket_popularity_protocol')
    log=io.StringIO();test_start=time.perf_counter()
    with contextlib.redirect_stdout(log):outcome=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    test_elapsed=round(time.perf_counter()-test_start,6)
    if not outcome.wasSuccessful() or outcome.skipped:print(log.getvalue());raise ValueError('Protocol mutation tests failed')
    check(bound)
    within(ROOT,PRIVATE).mkdir()
    within(ROOT,VERIFY).mkdir(parents=True,exist_ok=True)
    with within(ROOT,VERIFY+'/tests.log').open('x',encoding='utf-8',newline='\n') as f:f.write(log.getvalue())
    scope={'real_statistic_fits':0,'real_ranked_queries':0,'real_metric_calculations':0,'data_CSV_rows_parsed':0,
           'reserved_test_enabled':False,'test_gate':'locked','baseline_and_evaluator_implemented':False}
    gate={'status':'locked_at_specification_freeze','protocol':descriptor(ROOT,POLICY),'test_ranking_started':False,
          'logical_tests_consumed':0,'note':'Immutable initial-state receipt; future execution uses separately guarded usage journal, never edits this freeze receipt'}
    write_new(PRIVATE+'/initial_test_gate.json',gate)
    spec={'status':'execution_protocol_v1_frozen_before_implementation','date_asia_taipei':'2026-10-28',
          'protocol':descriptor(ROOT,POLICY),'sources':bound,'source_verification':'all accepted sources/outputs read as bytes and SHA/size checked; data CSVs not parsed',
          'policy_consistency_checks':checks,'scope':scope,
          'tests':{'tests_run':outcome.testsRun,'failures':len(outcome.failures),'errors':len(outcome.errors),'skips':len(outcome.skipped),'elapsed_seconds':test_elapsed},
          'initial_test_gate':descriptor(ROOT,PRIVATE+'/initial_test_gate.json')}
    write_new(SPEC,spec)
    acceptance={'status':'protocol_consistency_sources_and_freeze_readback_passed','specification':descriptor(ROOT,SPEC),
        'checks_passed':len(checks),'checks':checks,'sources_verified':len(bound),'tests':spec['tests'],'scope':scope,
        'preserved_denominators':policy['fixed_denominators_from_accepted_build'],
        'elapsed_seconds':round(time.perf_counter()-started,6),
        'next_step':'implement baseline/evaluator with synthetic hand-counted independent oracles; then freeze real development execution; reserved-test remains locked'}
    write_new(ACCEPT,acceptance)
    outputs=[descriptor(ROOT,p) for p in (SPEC,ACCEPT,PRIVATE+'/initial_test_gate.json',VERIFY+'/tests.log')]
    write_new(PRIVATE+'/output_guard.json',{'sources':bound,'outputs':outputs})
    # JSON semantic round-trip plus byte-bound readback; no real ranking function exists.
    if read(SPEC)!=spec or read(ACCEPT)!=acceptance or read(PRIVATE+'/initial_test_gate.json')!=gate:raise ValueError('Freeze JSON roundtrip differs')
    check(outputs)
    return {'status':acceptance['status'],'sources':len(bound),'checks':len(checks),'tests':outcome.testsRun,'scope':scope}


def verify():
    guard=read(PRIVATE+'/output_guard.json');check(guard['sources']+guard['outputs'])
    checks=validate(read(POLICY),read('docs/contracts/retailrocket_recommendation_v1.json'),read('reports/stage8/retailrocket_build_v1.json'))
    return {'status':'frozen_protocol_and_source_bytes_verified','sources':len(guard['sources']),'checks':len(checks),
            'scope':read(ACCEPT)['scope'],'tests_rerun':False,'real_data_CSVs_parsed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--freeze',action='store_true');group.add_argument('--verify',action='store_true')
    args=parser.parse_args();print(json.dumps(freeze() if args.freeze else verify(),ensure_ascii=False,indent=2))
