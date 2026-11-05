"""Bounded vote diagnosis and paired V7 cost comparisons on sealed samples.

Run --acceptance, --profile, --compare48, and (only after a passing 48 result)
--compare34 in separate windows. All entry points keep the original V4 ranker
and previous scientific outputs available as immutable references.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median
import sqlite3
import sys
from time import perf_counter
import unittest
from uuid import uuid4

import psutil

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, check_gates, describe, environment, read, verify_bindings, write)
from scripts.retailrocket_session_knn_cost_window_v5 import run_window
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from scripts.retailrocket_session_knn_monitor_v3 import ThrottledWatch
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell
from scripts.retailrocket_session_knn_checks_v4 import clear_caches
from scripts.run_retailrocket_session_knn_refined_cost_v6 import _normal_exit, _same_payload
from scripts.run_retailrocket_session_knn_gap_v7 import public_json


MODULE = 'scripts.run_retailrocket_session_knn_vote_v7'
BASE = 'reports/stage12/retailrocket_session_knn_'
V6 = BASE+'v6_refined_cost_20261103.json'
SPEC = BASE+'v7_sql_vote_assessment_20261105.json'
GAP = BASE+'v7_gap_cost_20261105.json'
ACCEPT = BASE+'v7_vote_acceptance_20261105.json'
OUTPUT = {stage: BASE+'v7_vote_'+stage+'_20261105.json' for stage in ('profile', 'compare48', 'compare34')}
SUITES = ('tests.test_retailrocket_session_knn_vote_v7', 'tests.test_retailrocket_session_knn_vote_comparison_v7')
METHODS = ('scripts/run_retailrocket_session_knn_gap_v7.py','scripts/retailrocket_session_knn_gap_v7.py', 'scripts/retailrocket_session_knn_vote_v7.py', 'scripts/run_retailrocket_session_knn_vote_v7.py',
           *(name.replace('.', '/')+'.py' for name in SUITES))
PROFILE_ORDER = ('baseline', 'batch_fetch', 'profile', 'profile', 'batch_fetch', 'baseline')


def acceptance():
    root = ROOT/'shop-mysql-runtime/verification'/('knn-v7-vote-tests-'+uuid4().hex)
    root.mkdir()
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    start = perf_counter()
    with (root/'tests.log').open('x', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.testsRun or not result.wasSuccessful() or result.skipped:
        raise ValueError(f'Vote acceptance failed: {root/"tests.log"}')
    receipt = dict(status='vote_methods_synthetic_accepted', tests_run=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   seconds=perf_counter()-start, suites=list(SUITES), environment=environment(),
                   sqlite_version=sqlite3.sqlite_version, log=describe(root/'tests.log'),
                   methods=[describe(ROOT/name) for name in METHODS], reserved_test='locked')
    public_json(ROOT/ACCEPT, receipt, exclusive=True)
    print(json.dumps({'tests_run': result.testsRun, 'seconds': receipt['seconds']}))


def schedule(stage, candidate):
    if stage == 'profile':
        return [(f'diagnosis_{i}_{mode}', mode) for i, mode in enumerate(PROFILE_ORDER)]
    runs = [('warm_A', 'baseline'), ('warm_B', candidate)]
    for i in range(6):
        for arm in ('AB' if i % 2 == 0 else 'BA'):
            runs.append((f'pair_{i+1}_{arm}', 'baseline' if arm == 'A' else candidate))
    return runs


def _costs(measured, probes):
    rows = measured['queries']
    if len(rows) != len(probes) or measured['committed_prefix_rows'] != 0:
        raise ValueError('A fresh complete subset is required')
    for i,(row, probe) in enumerate(zip(rows, probes)):
        if (row['subset_ordinal'], row['original_ordinal'], row['key_sha256']) != (i, probe['original_ordinal'], probe['key_sha256']):
            raise ValueError('Reference roster and measurement differ')
    verify = sum(r['verification_seconds'] for r in rows)
    append = sum(r['append_without_commit_seconds'] for r in rows)
    commit = sum(c['seconds'] for c in measured['chunk_commits'])
    return {'primary_seconds': verify+append+commit, 'verification_seconds': verify,
            'append_excluding_commit_seconds': append, 'all_commit_seconds': commit,
            'rank_seconds': sum(r['rank_seconds'] for r in rows),
            'vote_seconds': sum(r['rank_stages_seconds']['sql_selected_votes_and_accumulation'] for r in rows),
            'setup_seconds': measured['setup_seconds'], 'tail_seconds': measured['tail_flush_and_eof_seal_seconds']}


def paired_decision(runs):
    """Apply the predeclared directional and magnitude gates to all six pairs."""
    pairs = []
    for i in range(1,7):
        a,b = (runs[f'pair_{i}_{arm}'] for arm in 'AB')
        if any(not math.isfinite(v) or v <= 0 for v in (a['primary_seconds'], b['primary_seconds'], a['entry_seconds'], b['entry_seconds'])):
            raise ValueError('Invalid measured duration')
        pairs.append({'pair': i, 'order': 'AB' if i%2 else 'BA',
                      'A_primary_seconds': a['primary_seconds'], 'B_primary_seconds': b['primary_seconds'],
                      'primary_saving_seconds': a['primary_seconds']-b['primary_seconds'],
                      'primary_saving_percent': 100*(a['primary_seconds']-b['primary_seconds'])/a['primary_seconds'],
                      'entry_saving_seconds': a['entry_seconds']-b['entry_seconds']})
    by_order = {order: median(p['primary_saving_seconds'] for p in pairs if p['order']==order) for order in ('AB','BA')}
    wins = sum(p['primary_saving_seconds']>0 for p in pairs)
    pct = median(p['primary_saving_percent'] for p in pairs)
    whole = {arm: median(runs[f'pair_{i}_{arm}']['entry_seconds'] for i in range(1,7)) for arm in 'AB'}
    passes = wins>=5 and min(by_order.values())>0 and pct>=5
    return {'pairs': pairs, 'faster_pairs': wins, 'order_median_savings_seconds': by_order,
            'median_saving_percent': pct, 'primary_gate_passed': passes,
            'entry_median_seconds': whole, 'entry_regressed': whole['B']>whole['A'],
            'supports_candidate': passes and whole['B']<=whole['A']}


def _run(folder, request, label, mode, inputs, watch):
    from scripts.retailrocket_session_knn_vote_v7 import make_verifier
    selected, config, binding, model, database, probes, ordinals, reference = inputs
    run_root = folder/label
    start = perf_counter()
    store = DetailedTimedStore.create(run_root/'verified_subset', binding, request['deadline_utc'],
            request['budget_seconds'], source_root=ROOT, expected_queries=len(probes),
            required_stages=('reconstruction','queries'))
    profile = []
    verifier = make_verifier(mode, profile if mode=='profile' else None)
    with store.writer():
        store.seal_stage('reconstruction', {'kind':'reused_v5_reconstructed_model','fit_audit':model['fit_audit']})
        measured = verifier(selected/'primary', {k:selected/k for k in ('dataset','P0','C1','D1')},
                            config, store, model, database, ordinals, watch)
    store.detailed_cost_summary(measured)
    proof = ledger_proof(store, probes)
    _same_payload(proof, reference)
    _costs(measured, probes)
    write(run_root/'measured.json', measured)
    write(run_root/'observations.json', {'budget':store.budget_events, 'append':store.append_events})
    write(run_root/'profile.json', profile)
    write(run_root/'proof.json', proof)
    write(run_root/'entry.json', {'label':label,'mode':mode,'seconds':perf_counter()-start})


def worker(folder):
    request = read(folder/'request.json')
    meta = request['metadata']
    watch = ThrottledWatch(folder, request['deadline_utc'])
    try:
        def verify_sources(phase):
            start = perf_counter()
            verify_bindings(request['sources'], watch)
            check_gates()
            write(folder/(phase+'_hash.json'), {'count':len(request['sources']), 'seconds':perf_counter()-start})

        verify_sources('initial')
        if (meta['environment'] != environment() or meta['sqlite_version'] != sqlite3.sqlite_version):
            raise ValueError('Benchmark environment differs')
        selected = ROOT/meta['selected_root']
        config = read(selected/'configuration.json')
        binding = read(ROOT/meta['old_run'])['binding']
        probes = read(ROOT/meta['probes'])['probes']
        ordinals = read(selected/'ordinals.json')
        expected = 34 if meta['stage']=='compare34' else 48
        if len(probes)!=expected or len(ordinals)!=expected or config['fixed_validation']['queries']!=expected:
            raise ValueError('Fixed sample size differs')
        model_root = ROOT/meta['model_root']
        model = read(model_root/'reconstruction.json')['receipt']
        reference = read(ROOT/meta['reference'])
        inputs = (selected, config, binding, model, model_root/'independent.sqlite', probes, ordinals, reference)
        clear_caches()
        for label,mode in schedule(meta['stage'],meta['candidate']):
            watch.force()
            write(folder/(label+'_started.json'), {'label':label,'mode':mode})
            _run(folder,request,label,mode,inputs,watch)
            watch.force()
        verify_sources('final')
        write(folder/'done.json', {'stage':meta['stage'],'completed':True,'scope':len(probes)})
    except BaseException as exc:
        write(folder/'failure.json', {'error_type':type(exc).__name__, 'full_readback_started':False})
        raise


def _profile_rollup(profile, measured):
    totals = defaultdict(float)
    if len(profile) != len(measured['queries']):
        raise ValueError('Incomplete per-query diagnosis')
    for part, row in zip(profile,measured['queries']):
        values = part['parts_seconds']
        if (part['outer_seconds'] != row['rank_stages_seconds']['sql_selected_votes_and_accumulation']
                or any(not math.isfinite(x) or x<0 for x in values.values())
                or not math.isclose(sum(values.values()),part['outer_seconds'],rel_tol=1e-8,abs_tol=1e-9)):
            raise ValueError('Invalid vote partition')
        work=row['sql_workload']
        for field, work_field in [('selected_rows','sql_selected_rows_inserted'),('membership_rows','sql_vote_membership_rows_returned'),
                                 ('additions','exact_vote_additions')]:
            if part[field]!=work[work_field]:
                raise ValueError('Profile operation count differs')
        for name,value in values.items():
            totals[name]+=value
    return dict(totals)


def publish(folder):
    from scripts.retailrocket_session_knn_vote_v7 import choose_candidate
    receipt=read(folder/'supervisor_completion.json')
    _normal_exit(receipt)
    for ident in read(folder/'tracked_process_identities.json')['identities']:
        if psutil.pid_exists(ident['pid']):
            try:
                if psutil.Process(ident['pid']).create_time()==ident['create_time']:
                    raise ValueError('A recorded worker identity remains active')
            except psutil.NoSuchProcess:
                pass
    req=read(folder/'request.json')
    m=req['metadata']; stage=m['stage']
    if not read(folder/'done.json')['completed']:
        raise ValueError('Incomplete benchmark')
    probes=read(ROOT/m['probes'])['probes']; reference=read(ROOT/m['reference'])
    runs={}; profiles=[]; tables={}; operations={}; raw={}
    for label,mode in schedule(stage,m['candidate']):
        root=folder/label
        run=read(root/'verified_subset/run.json')
        if run['deadline_utc']!=req['deadline_utc'] or run['budget_seconds']!=req['budget_seconds']:
            raise ValueError('Benchmark clock was reset')
        store=DetailedTimedStore.open(root/'verified_subset',run['binding'],source_root=ROOT)
        proof=ledger_proof(store,probes)
        _same_payload(proof,reference)
        if proof!=read(root/'proof.json'):
            raise ValueError('Post-exit proof differs')
        measured=read(root/'measured.json')
        obs=read(root/'observations.json')
        store.commit_events=measured['chunk_commits'];store.append_events=obs['append'];store.budget_events=obs['budget']
        store.detailed_cost_summary(measured)
        costs=_costs(measured,probes)
        entry=read(root/'entry.json')
        if (entry['label'],entry['mode'])!=(label,mode):
            raise ValueError('Order/implementation differs')
        runs[label]=dict(costs,mode=mode,entry_seconds=entry['seconds'])
        raw[label]=measured['queries']
        events=read(root/'profile.json')
        if mode=='profile':
            tables[label]=_profile_rollup(events,measured)
            operations[label]={field:sum(event[field] for event in events) for field in
                               ('selected_rows','membership_rows','additions','fetch_batches')}
            operations[label]['fraction_queries']=sum(event['fallback'] for event in events)
            operations[label]['max_scale_bits']=max(event['scale_bits'] for event in events)
            profiles.extend(events)
        elif events:
            raise ValueError('Detailed timers active in a timed candidate')
    reference_work = [r['sql_workload'] for r in next(iter(raw.values()))]
    if any([r['sql_workload'] for r in rows] != reference_work for rows in raw.values()):
        raise ValueError('Logical workload differs across equivalent implementations')
    hashes={p:read(folder/(p+'_hash.json')) for p in ('initial','final')}
    if any(v['count']!=len(req['sources']) for v in hashes.values()):
        raise ValueError('Incomplete source inventory')
    report={'stage':stage,'namespace':folder.relative_to(ROOT).as_posix(),'supervisor':receipt,
            'environment':m['environment'],'sqlite_version':m['sqlite_version'],'sources_bound':len(req['sources']),
            'hash_checks':hashes,'all_scientific_bytes_match_reference':True,
            'reference':{k:reference[k] for k in ('records','actual_committed_bytes','actual_committed_payload_sha256')},
            'runs':runs,'original_distinct_sample_size':len(probes),'repeat_query_checks':len(runs)*len(probes),
            'new_unique_keys':0,'new_primary_fit_validation_bootstrap':0,'gates':check_gates(),'T_plan':None}
    if stage=='profile':
        report['profile_parts_seconds']=tables
        report['profile_operation_counts']=operations
        report['selected_candidate']=choose_candidate(profiles)
        report['actionable_seconds_across_profiles']={
            'batch_insert':sum(t['temp_insert'] for t in tables.values()),
            'batch_fetch':sum(t['cursor_execute']+t['cursor_fetch'] for t in tables.values()),
            'rank_counts':sum(t['accumulate']+t['check'] for t in tables.values())}
        report['mode_median_vote_seconds']={mode:median(r['vote_seconds'] for r in runs.values() if r['mode']==mode)
                                           for mode in sorted(set(PROFILE_ORDER))}
    else:
        report['candidate']=m['candidate'];report['decision']=paired_decision(runs)
        cells=defaultdict(list)
        for i in range(1,7):
            for j,p in enumerate(probes):
                a,b=(raw[f'pair_{i}_{arm}'][j] for arm in 'AB')
                cell=p['cell'] if stage=='compare34' else _cell(p,p['cell'],'neighbor_vote_grid')
                cells[cell].append(tuple(row['verification_seconds']+row['append_without_commit_seconds']
                                         for row in (a,b)))
        grid=read(ROOT/V6)['repeats'][0]['refinement_sensitivity']['policies']['neighbor_vote_grid']['cells']
        report['cell_paired_rows_excluding_commit']={}
        for key, ref in grid.items():
            pairs=cells.get(key,[])
            savings=[a-b for a,b in pairs]
            report['cell_paired_rows_excluding_commit'][key]={
                'population':ref['population_queries'],'measured_queries':len(pairs)//6,
                'worst_A_seconds':max((a for a,b in pairs),default=None),
                'worst_B_seconds':max((b for a,b in pairs),default=None),
                'worst_saving_seconds':min(savings,default=None),
                'median_saving_seconds':median(savings) if savings else None}
        if sum(v['measured_queries'] for v in report['cell_paired_rows_excluding_commit'].values())!=len(probes):
            raise ValueError('Fixed sample did not map completely to frozen V6 grid')
    report['evidence']=[describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]
    public_json(ROOT/OUTPUT[stage],report,exclusive=True)
    print(json.dumps({'stage':stage,'report':OUTPUT[stage],'elapsed':receipt['seconds'],
                      'candidate':report.get('selected_candidate',m['candidate']),'decision':report.get('decision')}))


def supervise(stage):
    if (ROOT/OUTPUT[stage]).exists():
        raise FileExistsError(ROOT/OUTPUT[stage])
    acc=read(ROOT/ACCEPT)
    if (acc['status']!='vote_methods_synthetic_accepted' or acc['environment']!=environment()
            or acc['sqlite_version']!=sqlite3.sqlite_version or {r['path'] for r in acc['methods']}!=set(METHODS)):
        raise ValueError('Current vote tools must pass acceptance')
    verify_bindings(acc['methods'])
    check_gates()
    base=read(ROOT/V6)
    anchors={r['path']:r for r in base['evidence']}
    names=[base['namespace']+'/'+name for name in ('request.json','supervisor_completion.json')]
    verify_bindings([anchors[n] for n in names])
    _normal_exit(read(ROOT/names[1]))
    prev=read(ROOT/names[0]); orig=prev['metadata']
    records={r['path']:r for r in prev['sources']}
    gap=read(ROOT/GAP)
    if gap.get('status')!='v7_gap_34_measured_twice' or gap['scope']['new_keys']!=34 or not gap['sources_reverified_before_after']:
        raise ValueError('Completed gap evidence required')
    records.update((r['path'],r) for r in acc['methods']+[anchors[n] for n in names])
    sources=[ACCEPT,V6,GAP,SPEC]
    meta={'stage':stage,'candidate':None,'sqlite_version':sqlite3.sqlite_version,'environment':environment(),
          'model_root':orig['independent_model_folder'],'selected_root':orig['joint_raw_selected_inputs'],
          'old_run':orig['joint_verified_run'],'probes':orig['joint_frozen_probes'],'reference':orig['joint_original_ledger_proof']}
    if environment()!=orig['environment'] or read(ROOT/SPEC)['static_inspection']['sqlite_version']!=sqlite3.sqlite_version:
        raise ValueError('Reference host environment differs')
    gap_root=gap['namespace']
    pinned={r['path']:r for r in gap['evidence']}
    gap_exit=pinned[gap_root+'/supervisor_completion.json']
    verify_bindings([gap_exit]);_normal_exit(read(ROOT/gap_exit['path']))
    records[gap_exit['path']]=gap_exit
    if stage!='profile':
        diagnostic=read(ROOT/OUTPUT['profile'])
        if diagnostic['stage']!='profile' or not diagnostic['all_scientific_bytes_match_reference']:
            raise ValueError('Completed diagnosis required')
        meta['candidate']=diagnostic['selected_candidate'];sources.append(OUTPUT['profile'])
    if stage=='compare34':
        prior=read(ROOT/OUTPUT['compare48'])
        if not prior['decision']['supports_candidate'] or prior['candidate']!=meta['candidate']:
            raise ValueError('Original 48 did not support low-band comparison')
        sources.append(OUTPUT['compare48'])
        meta.update(selected_root=gap_root+'/raw_selected_inputs',probes=gap_root+'/frozen_probes.json',
                    old_run=gap_root+'/repeat_0/verified_subset/run.json',reference=gap_root+'/repeat_0/proof.json')
        records.update((k,v) for k,v in pinned.items() if k.startswith(meta['selected_root']+'/') or k in
                       (meta['probes'],meta['reference'],meta['old_run']))
        verify_bindings([pinned[meta['old_run']],pinned[meta['reference']],pinned[meta['probes']]])
        for source in read(ROOT/meta['old_run'])['binding']['sources']:
            if source!=records.get(source['path']):
                # The original input contract may also bind a seal under the gap namespace.
                if source!=pinned.get(source['path']):
                    raise ValueError('Missing gap source provenance: '+source['path'])
                records[source['path']]=source
    for path in sources:
        records[path]=describe(ROOT/path)
    folder=ROOT/'shop-mysql-runtime/verification'/('knn-v7-vote-'+stage+'-'+uuid4().hex)
    print('V7 vote window: '+folder.relative_to(ROOT).as_posix(),flush=True)
    receipt=run_window(folder,[sys.executable,'-B','-m',MODULE,'--worker',str(folder)],
                       [records[k] for k in sorted(records)],'joint_tail',metadata=meta)
    if receipt['exit_code']!=0:
        print(str(folder),file=sys.stderr)
    _normal_exit(receipt)
    publish(folder)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance',action='store_true')
    for stage in OUTPUT:
        modes.add_argument('--'+stage,action='store_true')
    modes.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:
        worker(args.worker)
    elif args.acceptance:
        acceptance()
    else:
        supervise(next(stage for stage in OUTPUT if getattr(args,stage)))
