"""V2 exact readback of immutable V1 output with a replayable verified ledger.

Only frozen independent oracles are shared; production rank/loader/evaluator
helpers are never imported. V1 files and partial namespaces are read-only.
"""
from collections import Counter
from bisect import bisect_left
from decimal import Decimal
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from scripts.retailrocket_session_knn_readback import (
    rows, ids, positive_table, reconstruct, FourFold, scalar_count,
    read_rows, num, terms, close, GROUPS, METRICS, FIELDS, check_bootstrap, exact, dump)
from scripts import retailrocket_session_knn_sql_v2 as sql


def seal_consistent(store,name,receipt):
    previous=store.get_stage(name)
    if previous is None:store.seal_stage(name,receipt)
    else:exact(previous,receipt)


def prepare_model(primary, paths, config, store, watch=lambda:None, fault=lambda point:None):
    stage=store.get_stage('reconstruction')
    database=store.folder/'independent.sqlite'
    if stage is not None:
        return stage
    if database.exists():
        # Incomplete DB is evidence only. Never reuse an unsealed reconstruction.
        archive=store.folder/('uncommitted-db-'+str(len(list(store.folder.glob('uncommitted-db-*')))))
        archive.mkdir()
        for suffix in ('','-wal','-shm','-journal'):
            old=Path(str(database)+suffix)
            if old.exists():old.rename(archive/old.name)
    with database.open('xb'): pass
    db=sqlite3.connect(database)
    db.set_progress_handler(lambda:(watch() or 0),10000)
    try:
        fault('database_build')
        def reconstruction_watch():
            watch();fault('database_row')
        sessions,support,audit=reconstruct(db,primary,paths['dataset'],paths['C1'],config,reconstruction_watch)
        del sessions
        sql.build_index(db,watch)
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()!=('ok',):
            raise ValueError('Independent database integrity check failed')
    finally:
        db.close()
    if any(Path(str(database)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('Unsealed database journal remains')
    stage={'fit_audit':audit,'support':support,'model_method':'raw_baskets_SQL_DISTINCT_membership_v2'}
    store.seal_stage('reconstruction',stage,artifacts=('independent.sqlite',))
    return stage


def load_context(paths,config,support,watch=lambda:None):
    counts=positive_table(paths['P0']/'item_counts.csv',FIELDS['item_counts.csv'],watch)
    if set(counts)!=set(support) or any(counts[i]<support[i] for i in support):
        raise ValueError('Oracle P0/C1 support mismatch')
    catalog={}
    for row in read_rows(paths['dataset']/'catalog.csv',config['schemas']['catalog.csv']):
        watch(); i=row['itemid'];num(i);t=num(row['first_view_ms'])
        if i in catalog: raise ValueError('Oracle duplicate catalog')
        catalog[i]=t
    if any(i not in catalog or catalog[i]>=config['train_window_ms'][1] for i in support):
        raise ValueError('Oracle train catalog clock')
    return counts,catalog


def verify_queries(primary,paths,config,store,model,watch=lambda:None,fault=lambda point:None):
    source,p0,c1,d1=(paths[x] for x in ('dataset','P0','C1','D1'))
    audit=model['fit_audit']; support=model['support']
    counts,catalog=load_context(paths,config,support,watch)
    prepared=sql.prepare_catalog(catalog,counts,watch)
    first_times=sorted(catalog.values())
    db=sqlite3.connect('file:'+str((store.folder/'independent.sqlite').resolve()).replace('\\','/')+'?mode=ro',uri=True)
    db.set_progress_handler(lambda:(watch() or 0),10000)
    try:
        controls=[iter(read_rows(p0/name,FIELDS[name])) for name in ('ranked_queries.csv','query_metrics.csv','query_slices.csv')]
        controls += [iter(rows(c1/'queries.jsonl',watch)),iter(rows(d1/'queries.jsonl',watch))]
        outputs=iter(rows(primary/'queries.jsonl',watch)); previous=None; checked=scalars=candidate_scores=0
        committed=store.recover()['records']; saved=iter(store.iter_records()); ordinal=-1
        lo,hi=config['validation_window_ms']
        for raw in read_rows(source/'queries.csv',config['schemas']['queries.csv']):
            watch()
            if raw['role']!='validation': continue
            ordinal+=1
            if ordinal<committed:
                record=next(saved)
                key=[raw['visitorid'],num(raw['session_start_ms']),num(raw['query_ms'])]
                exact(record['key'],key)
                if any(next(stream,None) is None for stream in [*controls,outputs]):
                    raise ValueError('Missing source row while replaying committed prefix')
                previous=tuple(key)
                continue
            v=raw['visitorid'];num(v);s,t,nt,index=(num(raw[f]) for f in ('session_start_ms','query_ms','next_view_ms','basket_index'))
            key=(v,s,t)
            if previous is not None and key<=previous: raise ValueError('Oracle duplicate/unordered query')
            previous=key
            if not lo<=t<nt<hi or s>t or nt-t>1800000 or t+1800000>hi:
                raise ValueError('Oracle validation clock/horizon')
            for f,value in [('status','labelled'),('next_role','validation'),('next_in_session','1'),('mature','1'),('cross_role','0')]:
                if raw[f]!=value: raise ValueError('Oracle query label state')
            current=db.execute('SELECT k,n FROM h WHERE v=? AND s=? AND t=?',key).fetchone()
            if current is None or current[0]!=index: raise ValueError('Oracle missing current basket')
            history=set()
            for (text,) in db.execute('SELECT items FROM h WHERE v=? AND s=? AND t<=? ORDER BY t',key):
                watch();history.update(json.loads(text))
            history=sorted(history,key=int); targets=ids(raw['target_items'])
            successor=db.execute('SELECT t,k,role,items FROM h WHERE v=? AND s=? AND t>? ORDER BY t LIMIT 1',key).fetchone()
            if successor is None or successor[:3]!=(nt,index+1,'validation'):
                raise ValueError('Oracle next-basket identity')
            exact(sorted(targets,key=int),sorted(json.loads(successor[3]),key=int))
            reachable=sum(i in catalog and catalog[i]<t for i in targets); candidate=bisect_left(first_times,t)
            if (len(targets)!=num(raw['target_count']) or reachable!=num(raw['reachable_target_count'])
                    or candidate!=num(raw['candidate_count']) or raw['all_targets_reachable']!=str(int(reachable==len(targets)))):
                raise ValueError('Oracle full query denominators')
            values=[next(stream,None) for stream in controls]; actual=next(outputs,None)
            if any(x is None for x in values) or actual is None: raise ValueError('Oracle missing paired row')
            rank,metric,slices,one,three=values
            for r in (rank,metric,slices):
                if (r['visitorid'],num(r['session_start_ms']),num(r['query_ms']))!=key or r['role']!='validation':
                    raise ValueError('Oracle original P0 key/role')
            if rank['fit_id']!=config['control_fit_ids']['P0']: raise ValueError('Oracle P0 fit')
            p0ids=json.loads(rank['top10_items'])
            exact(json.loads(rank['top10_scores']),[counts.get(i,0) for i in p0ids])
            p0pred={'ids':p0ids,'candidate_count':num(rank['candidate_count'])}
            p0terms={m:float(metric[m]) for m in ('dcg','idcg',*METRICS)}
            p0terms.update(target_count=num(metric['target_count']),hits=num(metric['hits']),
                           first_hit_rank=num(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
            if num(metric['reachable_target_count'])!=reachable or metric['all_targets_reachable']!=raw['all_targets_reachable']:
                raise ValueError('Oracle P0 target denominator')
            train=num(raw['train_view_events']); known=sum(i in support for i in targets)
            activity='0' if not train else '1' if train==1 else '2-5' if train<=5 else '6+'
            if raw['visitor_seen_before_fit'] not in ('0','1') or raw['train_activity_slice']!=activity:
                raise ValueError('Oracle visitor/activity state')
            names={'visitor_history':'seen' if raw['visitor_seen_before_fit']=='1' else 'new',
                'current_basket':'multiple' if current[1]>1 else 'single','target_basket':'multiple' if len(targets)>1 else 'single',
                'train_activity':activity,'target_model':'all_positive' if known==len(targets) else 'all_zero' if not known else 'mixed'}
            identity={'key':list(key),'history':history,'history_sha256':hashlib.sha256(dump(history).encode()).hexdigest(),
                      'targets':targets,'candidate_count':candidate,'reachable_targets':reachable,'slices':names}
            for ref in (one,three):
                for f,value in identity.items(): exact(ref[f],value)
                exact(ref['predictions']['P0'],p0pred);exact(ref['terms']['P0'],p0terms)
            exact({f:slices[f] for f in GROUPS},names)
            exact(one['predictions']['C1'],three['predictions']['C1']);exact(one['terms']['C1'],three['terms']['C1'])
            for arm in ('C1','D1'):
                if three['predictions'][arm]['fit_id']!=config['control_fit_ids'][arm]: raise ValueError('Oracle control fit')
            def query_watch():
                watch();fault('query_work')
            pred=dict(three['predictions'],K1=sql.predict(db,support,audit['fit_id'],prepared.counts,prepared,t,history,(v,s),query_watch))
            binary={};precise={}
            for arm in ('P0','C1','D1','K1'):
                prediction=pred[arm]
                if (prediction['candidate_count']!=candidate or len(prediction['ids'])!=min(10,candidate)
                        or any(i not in catalog or catalog[i]>=t for i in prediction['ids'])):
                    raise ValueError('Oracle complete causal control/K1 list')
                independently,precise[arm]=terms(prediction['ids'],targets)
                if any(type(actual['terms'][arm][m]) is not float or not math.isfinite(actual['terms'][arm][m])
                       for m in ('dcg','idcg',*METRICS)):
                    raise ValueError('Oracle expected finite binary64 metric fields')
                close(actual['terms'][arm],independently)
                binary[arm]=actual['terms'][arm] if arm=='K1' else three['terms'][arm]
                if arm!='K1': exact(actual['terms'][arm],binary[arm])
            delta={'K1_minus_'+a:{m:binary['K1'][m]-binary[a][m] for m in METRICS} for a in ('C1','P0','D1')}
            expected=dict(identity,predictions=pred,terms=binary,delta=delta);exact(actual,expected)
            if pred['K1']['fallback_reason'] is not None: exact(pred['K1']['ids'],pred['P0']['ids'])
            payload={'expected':expected,
                'precise':{arm:{m:str(value) for m,value in metrics.items()} for arm,metrics in precise.items()},
                'delta_hex':{arm:{m:value.hex() for m,value in metrics.items()} for arm,metrics in delta.items()}}
            store.append_verified(ordinal,list(key),payload)
            fault('query_verified')
        if any(next(stream,None) is not None for stream in [*controls,outputs]): raise ValueError('Oracle extra paired row')
        store.flush_chunk()
        if ordinal+1!=config['fixed_validation']['queries']:
            raise ValueError('Incomplete full validation query coverage')
        seal_consistent(store,'queries',{'queries':ordinal+1,'paired_streams_eof_checked':True})
        return {'queries':ordinal+1}
    finally:
        db.close()


def replay_global(primary,paths,config,store,model,watch=lambda:None,fault=lambda point:None):
    _,catalog=load_context(paths,config,model['support'],watch)
    main=FourFold(catalog); conditional=FourFold(catalog)
    groups={f:{g:FourFold(catalog) for g in names} for f,names in GROUPS.items()}
    diagnostics={name:Counter() for name in ('history_size','unknown_seeds','eligible_neighbors','current_session_excluded',
        'selected_neighbor_count','boundary_ties_excluded','positive_candidates','zero_fill_slots','fallback_reason')}
    cross=Counter();roster=hashlib.sha256();deltas=[];checked=scalars=candidate_scores=0
    for record in store.iter_records():
        watch();fault('global_replay')
        payload=record['payload'];expected=payload['expected'];key=expected['key']
        exact(record['key'],key)
        pred=expected['predictions'];names=expected['slices'];targets=expected['targets']
        v,s,t=key;reachable=expected['reachable_targets'];candidate=expected['candidate_count']
        precise={arm:{m:Decimal(value) for m,value in metrics.items()} for arm,metrics in payload['precise'].items()}
        delta={arm:{m:float.fromhex(value) for m,value in metrics.items()} for arm,metrics in payload['delta_hex'].items()}
        exact(delta,expected['delta'])
        q={'v':v,'t':t,'targets':targets};main.add(q,pred,precise,delta,reachable)
        if reachable==len(targets):conditional.add(q,pred,precise,delta,reachable)
        for f,g in names.items():groups[f][g].add(q,pred,precise,delta,reachable)
        for name in diagnostics:
            value=pred['K1'][name]
            diagnostics[name][(value or 'positive_evidence') if name=='fallback_reason' else str(value)]+=1
        cross[dump([pred['K1']['fallback_reason'] is not None,pred['C1']['positive_candidates']==0,
            pred['D1']['positive_candidates']==0,names['target_model']])]+=1
        roster.update((dump(key)+'\n').encode());deltas.append((v,delta['K1_minus_C1']['ndcg']))
        checked+=1;scalars+=scalar_count(expected);candidate_scores+=candidate
    fault('bootstrap')
    def bootstrap_watch():
        watch();fault('bootstrap_draw')
    floor=max(50,math.ceil(checked/100)); result={'main':main.result(),'conditional':conditional.result(),'slices':{},
        'support_floor_queries':floor,'diagnostics':{k:dict(v) for k,v in diagnostics.items()},
        'fallback_cold_cross_tabs':dict(cross),'roster_sha256':roster.hexdigest(),
        'uncertainty':check_bootstrap(primary/'bootstrap.jsonl',paths['C1']/'bootstrap.jsonl',deltas,bootstrap_watch)}
    for f,buckets in groups.items():
        result['slices'][f]={}
        for g,fold in buckets.items():
            summary=fold.result();n=summary['queries']
            result['slices'][f][g]=dict(summary,support='empty' if not n else 'descriptive_only' if n<floor else 'sufficient_query_count')
    fixed=config['fixed_validation'];main_result=result['main']['arms']['K1']
    for name in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries','candidate_union_items'):
        exact(main_result[name],fixed[name])
    exact(floor,fixed['support_floor_queries'])
    for f,g,name in [('visitor_history','new','new_visitor_queries'),('current_basket','multiple','multi_item_current_queries'),('target_basket','multiple','multi_item_target_queries')]:
        exact(result['slices'][f][g]['queries'],fixed[name])
    exact({g:s['queries'] for g,s in result['slices']['target_model'].items()},fixed['target_model_query_counts'])
    for arm,reference in config['expected_controls'].items():
        old=dict(result['main']['arms'][arm],conditional=result['conditional']['arms'][arm],support_floor_queries=floor,
            slices={f:{g:dict(s['arms'][arm],support=s['support']) for g,s in buckets.items()} for f,buckets in result['slices'].items()})
        close(old,reference)
    close(json.loads((primary/'aggregate.json').read_text(encoding='utf-8')),result)
    seal_consistent(store,'global',{'queries':checked,'roster_sha256':roster.hexdigest()})
    seal_consistent(store,'bootstrap',result['uncertainty'])
    return {'status':'all_source_rows_model_postings_lineage_four_arm_queries_and_2000_draws_accepted',
        'fit_audit':model['fit_audit'],'aggregate':result,'queries_checked':checked,'query_nested_scalars_checked':scalars,
        'ranking_method':'independent_SQL_positive_overlap_exact_v2','candidate_scores_checked':candidate_scores,
        'bootstrap_replicates':result['uncertainty']['replicates'],'production_K1_helpers_imported':False,
        'sampled_oracle':False}


def verify(primary,paths,config,store,watch=lambda:None,fault=lambda point:None):
    if (store.folder/'candidate.json').exists():store.supersede_candidate()
    model=prepare_model(primary,paths,config,store,watch,fault)
    verify_queries(primary,paths,config,store,model,watch,fault)
    result=replay_global(primary,paths,config,store,model,watch,fault)
    fault('before_candidate')
    store.write_candidate(result)
    return result
