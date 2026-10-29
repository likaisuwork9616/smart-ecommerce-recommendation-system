"""Full raw-source SQL K1 readback. No K1 production/loader/evaluator imports."""
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import sqlite3

from scripts.retailrocket_popularity_oracle import read_rows, num, terms, Fold, close, GROUPS, METRICS, FIELDS
from scripts.retailrocket_directed_oracle import check_bootstrap
from scripts.retailrocket_session_knn_oracle import exact, dump


def rows(path, watch=lambda: None):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            watch(); value = json.loads(line)
            if type(value) is not dict:
                raise ValueError('Oracle JSONL object required')
            yield value


def ids(text):
    value = json.loads(text)
    if type(value) is not list or not value or len(set(value)) != len(value):
        raise ValueError('Oracle nonempty distinct items required')
    for i in value: num(i)
    return value


def positive_table(path, header, watch):
    result = {}
    for r in read_rows(path, header):
        watch(); i = r[header[0]]; num(i); n = num(r[header[1]])
        if i in result or n < 1: raise ValueError('Oracle duplicate/nonpositive support')
        result[i] = n
    return result


def reconstruct(db, folder, source, c1, config, watch):
    db.execute('CREATE TABLE h(v TEXT,s INTEGER,t INTEGER,k INTEGER,role TEXT,items TEXT,n INTEGER,PRIMARY KEY(v,s,t),UNIQUE(v,s,k))')
    db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
    previous = session = None; last_index = 0
    for r in read_rows(source/'baskets.csv', config['schemas']['baskets.csv']):
        watch()
        if r['role'] not in ('warmup', 'train', 'validation'): continue
        v = r['visitorid']; num(v)
        s, t, index = num(r['session_start_ms']), num(r['query_ms']), num(r['basket_index'])
        lo, hi = config['role_windows_ms'][r['role']]; key = (v,s,t)
        if not lo <= t < hi or s > t or (previous is not None and key <= previous):
            raise ValueError('Oracle history clock/order')
        if session != (v,s): last_index = 0
        if index != last_index+1: raise ValueError('Oracle nonconsecutive history index')
        previous, session, last_index = key, (v,s), index
        members = ids(r['items'])
        db.execute('INSERT INTO h VALUES(?,?,?,?,?,?,?)', (v,s,t,index,r['role'],dump(members),len(members)))
        if r['role'] == 'train':
            db.executemany('INSERT OR IGNORE INTO m VALUES(?,?,?)', ((v,s,i) for i in members))
    db.execute('CREATE INDEX posting ON m(i,v,s)')
    db.commit()
    sessions = {}
    for v,s,i in db.execute('SELECT v,s,i FROM m ORDER BY v,s,i'):
        watch(); sessions.setdefault((v,s),set()).add(i)
    support = dict(db.execute('SELECT i,COUNT(*) FROM m GROUP BY i'))
    exact(support, positive_table(c1/'support.csv', ['itemid','support'], watch))
    start,end = config['train_window_ms']
    digest = hashlib.sha256(f'K1_Jaccard_exact_session_k500_v1\n{start},{end}\n'.encode())
    saved = iter(rows(folder/'sessions.jsonl', watch))
    for key in sorted(sessions, key=lambda x:(int(x[0]),x[1])):
        watch(); items = sorted(sessions[key], key=int)
        exact(next(saved, None), {'key':list(key), 'items':items})
        digest.update((dump([list(key),items])+'\n').encode())
    if next(saved,None) is not None: raise ValueError('Oracle extra session')
    saved = iter(rows(folder/'postings.jsonl',watch))
    for i in sorted(support, key=int):
        watch()
        posting = [[v,s] for v,s in db.execute('SELECT v,s FROM m WHERE i=? ORDER BY CAST(v AS INTEGER),s',(i,))]
        exact(next(saved,None), {'itemid':i, 'sessions':posting, 'support':support[i]})
    if next(saved,None) is not None: raise ValueError('Oracle extra posting')
    saved = iter(rows(folder/'train_sessions.jsonl',watch)); original = iter(rows(c1/'train_sessions.jsonl',watch))
    for v,s,n,o in db.execute("SELECT v,s,COUNT(*),SUM(n) FROM h WHERE role='train' GROUP BY v,s ORDER BY v,s"):
        watch(); row = {'key':[v,s],'items':sorted(sessions[v,s],key=int),'baskets':n,'basket_memberships':o}
        exact(next(saved,None),row); exact(next(original,None),row)
    if next(saved,None) is not None or next(original,None) is not None: raise ValueError('Oracle extra lineage')
    n,occurrences = db.execute("SELECT COUNT(*),COALESCE(SUM(n),0) FROM h WHERE role='train'").fetchone()
    audit = {'start_ms':start,'end_ms':end,'train_sessions':len(sessions),
        'singleton_sessions':sum(len(v)==1 for v in sessions.values()),'train_baskets':n,
        'basket_item_memberships':occurrences,'distinct_session_item_memberships':sum(support.values()),
        'positive_support_items':len(support),'maximum_session_items':max(map(len,sessions.values()),default=0),
        'maximum_posting_size':max(support.values(),default=0),'fit_id':digest.hexdigest()}
    exact(json.loads((folder/'fit_audit.json').read_text(encoding='utf-8')),audit)
    for field,value in config['train_cost_audit'].items(): exact(audit[field],value)
    return sessions,support,audit


def predict(sessions,support,fit_id,counts,catalog,time,history,current,watch):
    h=set(history); pool=[]; visits=excluded=0
    # Every train session, including every zero-overlap session, is visited.
    for key,items in sessions.items():
        watch(); intersection=len(h & items); visits+=intersection
        if key==current:
            excluded+=int(intersection>0); continue
        if intersection:
            union=len(h | items); pool.append((key,intersection,union,Fraction(intersection,union)))
    digest=hashlib.sha256()
    for key,a,b,_ in sorted(pool,key=lambda r:(int(r[0][0]),r[0][1])):
        watch(); digest.update((dump([list(key),a,b])+'\n').encode())
    pool.sort(key=lambda r:(-r[3],int(r[0][0]),r[0][1])); watch()
    selected=pool[:500]; boundary=selected[-1][3] if len(selected)==500 else None
    total_ties=removed=0
    for pos,row in enumerate(pool):
        watch()
        if boundary is not None and row[3]==boundary:
            total_ties+=1; removed+=pos>=500
    scores={}
    # Every causal candidate is scored independently against all chosen sessions.
    for i,first in catalog.items():
        watch()
        if first<time: scores[i]=sum((sim for key,_,_,sim in selected if i in sessions[key]),Fraction(0))
    order=sorted(scores,key=lambda i:(-scores[i],-counts.get(i,0),int(i)))[:10]; watch()
    positive=sum(x>0 for x in scores.values()); supported=sum(i in support for i in h)
    reason=None
    if not positive:
        reason=('no_supported_seed' if not supported else 'only_self_session_overlap' if not pool and excluded
                else 'no_eligible_positive_neighbor' if not pool else 'no_positive_causal_vote')
    return {'fit_id':fit_id,'ids':order,'scores':[[scores[i].numerator,scores[i].denominator] for i in order],
        'p0_counts':[counts.get(i,0) for i in order],'candidate_count':len(scores),'history_size':len(h),
        'supported_seeds':supported,'unknown_seeds':len(h)-supported,'raw_posting_visits':visits,
        'current_session_excluded':excluded,'eligible_neighbors':len(pool),'neighbor_pool_sha256':digest.hexdigest(),
        'selected_neighbors':[{'key':list(key),'intersection':a,'union':b,'similarity':[s.numerator,s.denominator]} for key,a,b,s in selected],
        'selected_neighbor_count':len(selected),'boundary_similarity':None if boundary is None else [boundary.numerator,boundary.denominator],
        'boundary_ties_total':total_ties,'boundary_ties_excluded':removed,
        'vote_memberships':sum(len(sessions[key]) for key,_,_,_ in selected),'positive_candidates':positive,
        'zero_fill_slots':sum(scores[i]==0 for i in order),'fallback_reason':reason}


class FourFold:
    def __init__(self,catalog):
        self.arms={a:Fold(catalog) for a in ('P0','C1','D1','K1')}
        self.deltas={a:{m:[] for m in METRICS} for a in ('C1','P0','D1')}
    def add(self,q,pred,precise,delta,reachable):
        for arm,fold in self.arms.items(): fold.add(q,pred[arm]['ids'],precise[arm],reachable)
        for a,metrics in self.deltas.items():
            for m,values in metrics.items(): values.append(delta['K1_minus_'+a][m])
    def result(self):
        arms={a:f.result() for a,f in self.arms.items()}; n=arms['K1']['queries']; contrasts={}
        for a,metrics in self.deltas.items():
            values={m:math.fsum(xs)/n if n else None for m,xs in metrics.items()}
            for m in ('visitor_macro_ndcg','catalog_coverage'):
                x,y=arms['K1']['metrics'][m],arms[a]['metrics'][m]
                values[m]=x-y if x is not None and y is not None else None
            contrasts['K1_minus_'+a]={'delta_metrics':values}
        return {'arms':arms,'comparisons':contrasts,'queries':n,'visitors':arms['K1']['visitors']}


def scalar_count(value):
    if isinstance(value,dict): return sum(scalar_count(v) for v in value.values())
    if isinstance(value,list): return sum(scalar_count(v) for v in value)
    return 1


def verify(folder,paths,config,watch=lambda:None):
    source,p0,c1,d1=(paths[x] for x in ('dataset','P0','C1','D1'))
    database=folder/'oracle.sqlite'
    with database.open('xb'): pass
    db=sqlite3.connect(database)
    db.set_progress_handler(lambda: (watch() or 0),10000)
    try:
        sessions,support,audit=reconstruct(db,folder,source,c1,config,watch)
        counts=positive_table(p0/'item_counts.csv',FIELDS['item_counts.csv'],watch)
        if set(counts)!=set(support) or any(counts[i]<support[i] for i in support):
            raise ValueError('Oracle P0/C1 support mismatch')
        catalog={}
        for row in read_rows(source/'catalog.csv',config['schemas']['catalog.csv']):
            watch(); i=row['itemid'];num(i); t=num(row['first_view_ms'])
            if i in catalog: raise ValueError('Oracle duplicate catalog')
            catalog[i]=t
        if any(i not in catalog or catalog[i]>=config['train_window_ms'][1] for i in support):
            raise ValueError('Oracle train catalog clock')
        controls=[iter(read_rows(p0/name,FIELDS[name])) for name in ('ranked_queries.csv','query_metrics.csv','query_slices.csv')]
        controls += [iter(rows(c1/'queries.jsonl',watch)),iter(rows(d1/'queries.jsonl',watch))]
        outputs=iter(rows(folder/'queries.jsonl',watch)); previous=None; checked=scalars=candidate_scores=0
        main=FourFold(catalog); conditional=FourFold(catalog)
        groups={f:{g:FourFold(catalog) for g in names} for f,names in GROUPS.items()}
        diagnostics={name:Counter() for name in ('history_size','unknown_seeds','eligible_neighbors','current_session_excluded',
                    'selected_neighbor_count','boundary_ties_excluded','positive_candidates','zero_fill_slots','fallback_reason')}
        cross=Counter(); roster=hashlib.sha256(); deltas=[]; lo,hi=config['validation_window_ms']
        for raw in read_rows(source/'queries.csv',config['schemas']['queries.csv']):
            watch()
            if raw['role']!='validation': continue
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
            reachable=sum(i in catalog and catalog[i]<t for i in targets); candidate=sum(first<t for first in catalog.values())
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
            pred=dict(three['predictions'],K1=predict(sessions,support,audit['fit_id'],counts,catalog,t,history,(v,s),watch))
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
            q={'v':v,'t':t,'targets':targets};main.add(q,pred,precise,delta,reachable)
            if reachable==len(targets): conditional.add(q,pred,precise,delta,reachable)
            for f,g in names.items(): groups[f][g].add(q,pred,precise,delta,reachable)
            for name in diagnostics:
                value=pred['K1'][name];diagnostics[name][(value or 'positive_evidence') if name=='fallback_reason' else str(value)]+=1
            cross[dump([pred['K1']['fallback_reason'] is not None,pred['C1']['positive_candidates']==0,
                        pred['D1']['positive_candidates']==0,names['target_model']])]+=1
            roster.update((dump(list(key))+'\n').encode());deltas.append((v,delta['K1_minus_C1']['ndcg']))
            checked+=1;scalars+=scalar_count(expected);candidate_scores+=candidate
        if any(next(stream,None) is not None for stream in [*controls,outputs]): raise ValueError('Oracle extra paired row')
        floor=max(50,math.ceil(checked/100)); result={'main':main.result(),'conditional':conditional.result(),'slices':{},
            'support_floor_queries':floor,'diagnostics':{k:dict(v) for k,v in diagnostics.items()},
            'fallback_cold_cross_tabs':dict(cross),'roster_sha256':roster.hexdigest(),
            'uncertainty':check_bootstrap(folder/'bootstrap.jsonl',c1/'bootstrap.jsonl',deltas,watch)}
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
        close(json.loads((folder/'aggregate.json').read_text(encoding='utf-8')),result)
        return {'status':'all_source_rows_model_postings_lineage_four_arm_queries_and_2000_draws_accepted',
            'fit_audit':audit,'aggregate':result,'queries_checked':checked,'query_nested_scalars_checked':scalars,
            'all_session_visits':checked*len(sessions),'candidate_scores_checked':candidate_scores,
            'bootstrap_replicates':result['uncertainty']['replicates'],'production_K1_helpers_imported':False,
            'sampled_oracle':False}
    finally:
        db.close()
