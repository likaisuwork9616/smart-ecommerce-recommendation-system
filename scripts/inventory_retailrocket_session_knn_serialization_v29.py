"""Saved C1 guard evidence plus isolated, byte-identical serialization replay; no rankings."""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import inspect
import math
from pathlib import Path
from statistics import median
from time import perf_counter,perf_counter_ns
import unittest
from uuid import uuid4
import psutil

from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.retailrocket_session_knn_sources_v24 import summarize_events

BASE='reports/stage12/retailrocket_session_knn_'
PARENT=BASE+'v28_compare_cost_20261109.json';ANALYSIS=BASE+'v28_compare_analysis_20261109.json';RELEASE=BASE+'v28_compare_release_20261109.json'
OUTPUT=BASE+'v29_serialization_inventory_20261109.json'
METHODS=('scripts/inventory_retailrocket_session_knn_serialization_v29.py','tests/test_retailrocket_session_knn_serialization_v29.py')
PLAN=dict(status='serialization_replay_plan_fixed_in_method',warmups=1,recorded_cycles=3,
    roles=['binding','config','model','identity_key','snapshot'],budget_seconds=180,maximum_dependency_bytes=16*2**20,
    maximum_rss_bytes=2*2**30,maximum_canonical_bytes=96*2**20,order='same five roles each cycle; all cycles retained',
    phases=['typed_tree_ns','json_and_tree_release_ns','utf8_and_text_release_ns','sha256_ns','comparison_ns'],
    interpretation='Isolated replay over the original fixed context. Not a new original48 window, C1 guard measurement, candidate comparison or speedup estimate.')


def measured_canonical(clock=perf_counter_ns):
    """Keep the frozen nested typed() verbatim; split only the final expression."""
    tree=ast.parse(inspect.getsource(c1.canonical));function=tree.body[0]
    if not isinstance(function.body[-1],ast.Return):raise ValueError('Frozen canonical shape changed')
    tail=ast.parse('''
start=_clock()
value_tree=typed(value)
typed_done=_clock()
text=json.dumps(value_tree,ensure_ascii=False,separators=(',',':'))
del value_tree
json_done=_clock()
data=text.encode('utf-8')
del text
end=_clock()
return data,dict(typed_tree_ns=typed_done-start,json_and_tree_release_ns=json_done-typed_done,
    utf8_and_text_release_ns=end-json_done,canonical_ns=end-start)
''').body
    function.body[-1:]=tail
    namespace=dict(c1.canonical.__globals__,_clock=clock)
    exec(compile(ast.fix_missing_locations(tree),'<frozen-canonical-phase-replay>','exec'),namespace)
    return namespace['canonical']


def operation_counts():
    # Cold: binding2 + key1 + config4 + model4 + snapshot3 =14.
    # Each hit: binding2 + key1 + config1 + model1 + snapshot2 =7.
    cold=dict(binding=2,identity_key=1,config=4,model=4,snapshot=3)
    hit=dict(binding=2,identity_key=1,config=1,model=1,snapshot=2)
    total={k:cold[k]+6*hit[k] for k in cold}
    return dict(cold=cold,each_hit=hit,all7=total,all7_canonical_calls=sum(total.values()),
        all7_digest_calls=total['identity_key']+total['snapshot'],
        interpretation='Frozen code-flow counts, checked on artificial C1 calls; not newly observed function counts in V28.')


def distribution(values):
    v=list(values);return dict(min=min(v),median=median(v),max=max(v),sum=math.fsum(v))


def inventory():
    if (ROOT/OUTPUT).exists():raise FileExistsError('Immutable inventory already exists; use --audit')
    report=read(ROOT/PARENT);analysis=read(ROOT/ANALYSIS);release=read(ROOT/RELEASE)
    verify_bindings([release['report'],*analysis['inputs']]);verify_bindings(report['evidence'])
    folder=ROOT/report['namespace'];request=read(folder/'request.json');source_map={x['path']:x for x in request['sources']}
    methods=[describe(ROOT/p) for p in METHODS]
    original=source_map['scripts/retailrocket_session_knn_reuse_v27.py'];verify_bindings([original])
    deps=request['metadata']['context']['dependencies'];verify_bindings(list(deps.values()))
    if sum(x['bytes'] for x in deps.values())>PLAN['maximum_dependency_bytes']:raise ValueError('Replay input limit exceeded')
    binding_path=request['metadata']['cohort']['old_run'];verify_bindings([source_map[binding_path]])
    binding=read(ROOT/binding_path)['binding'];config=read(ROOT/deps['config']['path']);model=read(ROOT/deps['model']['path'])['receipt']
    selected=ROOT/request['metadata']['cohort']['selected_root'];paths={k:selected/k for k in ('dataset','P0','C1','D1')}
    counts,catalog=pair.core.load_context(paths,config,model['support']);prepared=pair.sql.prepare_catalog(catalog,counts)
    snapshot=dict(first=prepared.first,counts=prepared.counts,first_times=prepared.first_times,fallback=prepared.fallback)
    expected_snapshot=report['results']['cache']['call_observations'][0]['snapshot_digest']
    if c1.digest(snapshot)!=expected_snapshot:raise ValueError('Rebuilt snapshot differs from original saved C1 digest')
    worker=read(folder/'worker_exit.json');context=request['metadata']['context']
    key=dict(binding=binding,sources=request['sources'],dependencies=context['dependencies'],methods=context['methods'],
        environment=request['metadata']['environment'],namespace=str(folder.resolve()),request=request,
        owner=[worker['pid'],worker['create_time']],source_root=str(ROOT.resolve()),method_root=str(ROOT.resolve()),config=config,model=model)
    values=dict(binding=binding,config=config,model=model,identity_key=key,snapshot=snapshot)
    evidence_rows=[]
    for item in request['metadata']['schedule']:
        if item['mode']!='C':continue
        events=read(folder/item['label']/'events.json');summary=summarize_events(events)
        if summary!=report['results']['runs'][item['label']]['diagnostic']:raise ValueError('Saved guard observations differ')
        phases={p:summary['phases'][p]['inclusive_wall_ns']/1e9 for p in ('cache.identity','cache.pre_use_digest','cache.final_guard')}
        evidence_rows.append(dict(label=item['label'],warmup=item['label'].startswith('warm_'),seconds=phases,
            nonoverlapping_guard_seconds=math.fsum(phases.values())))
    outdir=ROOT/'shop-mysql-runtime/verification'/('knn-v29-serialization-'+uuid4().hex);outdir.mkdir()
    public_json(outdir/'plan.json',dict(plan=PLAN,methods=methods,original_method=original),exclusive=True)
    tests=unittest.defaultTestLoader.loadTestsFromName('tests.test_retailrocket_session_knn_serialization_v29')
    with (outdir/'tests.log').open('x',encoding='utf-8') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(tests)
    if not result.wasSuccessful() or result.skipped:raise ValueError('Byte/exception/count tests failed')
    profiler=measured_canonical();start=perf_counter();process=psutil.Process();peak_rss=0
    goldens={name:c1.canonical(value) for name,value in values.items()}
    golden_digests={name:hashlib.sha256(value).hexdigest() for name,value in goldens.items()}
    if any(len(v)>PLAN['maximum_canonical_bytes'] for v in goldens.values()):raise ValueError('Canonical buffer limit exceeded')
    rows=[]
    for cycle in range(PLAN['warmups']+PLAN['recorded_cycles']):
        for name in PLAN['roles']:
            if perf_counter()-start>PLAN['budget_seconds']:raise TimeoutError('Replay budget exceeded')
            payload,timing=profiler(values[name]);tick=perf_counter_ns()
            if name in ('identity_key','snapshot'):
                actual=hashlib.sha256(payload).hexdigest();expected=golden_digests[name]
                hash_end=perf_counter_ns();equal=actual==expected
            else:
                hash_end=tick;equal=payload==goldens[name]
            compare_end=perf_counter_ns()
            if not equal or payload!=goldens[name]:raise ValueError('Instrumented canonical bytes differ')
            if timing['canonical_ns']!=sum(timing[k] for k in PLAN['phases'][:3]):raise ValueError('Phase time does not conserve')
            timing.update(sha256_ns=hash_end-tick,comparison_ns=compare_end-hash_end)
            peak_rss=max(peak_rss,process.memory_info().rss)
            if peak_rss>PLAN['maximum_rss_bytes']:raise MemoryError('Replay RSS exceeded')
            rows.append(dict(cycle=cycle,warmup=cycle<PLAN['warmups'],role=name,canonical_bytes=len(payload),phases_ns=timing))
    public_json(outdir/'rows.json',rows,exclusive=True)
    summary={name:dict(canonical_bytes=len(goldens[name]),phase_seconds={p:distribution(row['phases_ns'][p]/1e9 for row in rows if row['role']==name and not row['warmup'])
        for p in [*PLAN['phases'],'canonical_ns']}) for name in PLAN['roles']}
    call_counts=operation_counts();formal=[x for x in evidence_rows if not x['warmup']]
    verify_bindings([*methods,original,*deps.values()])
    output=dict(status='v29_C1_serialization_inventory_and_isolated_replay_complete',created_utc=datetime.now(timezone.utc).isoformat(),
        inputs=[describe(ROOT/p) for p in (PARENT,ANALYSIS,RELEASE)],methods=methods,original_method=original,
        saved_evidence=dict(files=len(report['evidence']),bytes=sum(x['bytes'] for x in report['evidence'])),
        plan=PLAN,tests=dict(run=result.testsRun,failures=0,errors=0,skipped=0,log=describe(outdir/'tests.log')),
        original_guard_observations=evidence_rows,formal_original_guard_seconds={p:distribution(x['seconds'][p] for x in formal) for p in formal[0]['seconds']},
        formal_original_guard_sum_seconds=distribution(x['nonoverlapping_guard_seconds'] for x in formal),
        code_flow_counts=call_counts,roles=summary,
        all7_structural_canonical_bytes=sum(call_counts['all7'][k]*len(goldens[k]) for k in call_counts['all7']),
        snapshot_rows=dict(catalog=len(prepared.first),counts=len(prepared.counts)),
        replay=dict(seconds=perf_counter()-start,peak_sampled_rss_bytes=peak_rss,original_snapshot_sha_matched=True,
            samples=len(rows),recorded_samples=sum(not x['warmup'] for x in rows),raw_rows=describe(outdir/'rows.json'),plan_receipt=describe(outdir/'plan.json')),
        identity_key_note='Historical key payload reconstructed from frozen request/config/model and private exited worker identity; original key digest was not saved. Snapshot digest is directly matched to saved C1.',
        scope=dict(real_original48_runs=0,rank_sql_append_calls=0,new_fit_validation_bootstrap=0,reserved_test='locked',
            full_validation_complete=False,covered_cells=55,distinct_comparable_queries=170,distinct_historical_queries=232),
        interpretation='Replay phase clocks and object retention perturb timing; JSON phase includes typed-tree release, UTF8 phase includes text release. Golden verification and checks add overhead. Do not apportion V28 seconds or claim candidate gains from this replay.',
        environment=environment(),gates=check_gates(),measured_speedup=None,T_plan=None)
    public_json(ROOT/OUTPUT,output,exclusive=True)
    print(dict(report=OUTPUT,tests=result.testsRun,canonical_calls=call_counts['all7_canonical_calls'],replay_seconds=output['replay']['seconds'],
        roles={k:{p:v['median'] for p,v in x['phase_seconds'].items()} for k,x in summary.items()}))


def audit():
    r=read(ROOT/OUTPUT)
    verify_bindings([*r['inputs'],*r['methods'],r['original_method'],r['tests']['log'],r['replay']['raw_rows'],r['replay']['plan_receipt']])
    if r['plan']!=PLAN or r['code_flow_counts']!=operation_counts() or r['scope']['real_original48_runs']!=0:raise ValueError('Inventory scope changed')
    print(dict(status=r['status'],tests=r['tests']['run'],real_original48_runs=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inventory',action='store_true');mode.add_argument('--audit',action='store_true')
    if parser.parse_args().audit:audit()
    else:inventory()
