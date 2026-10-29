"""Validation-only adapters, complete paired evaluation and exclusive artifacts."""
from collections import Counter
from contextlib import ExitStack
import csv
import hashlib
import json
import math
from dataclasses import replace

from scripts import retailrocket_cooccurrence as c
from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as old

ARTIFACTS = ('support.csv','pairs.csv','train_sessions.jsonl','queries.jsonl','bootstrap.jsonl','fit_audit.json','aggregate.json')


def dump(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def close(a,b):
    if isinstance(b,dict):
        if not isinstance(a,dict) or a.keys()!=b.keys():
            raise ValueError('Aggregate keys differ')
        for k in b: close(a[k],b[k])
    elif isinstance(b,list):
        if not isinstance(a,list) or len(a)!=len(b): raise ValueError('Aggregate list differs')
        for x,y in zip(a,b): close(x,y)
    elif type(b) is float:
        if type(a) not in (float,int) or not math.isfinite(a) or not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12):
            raise ValueError('Aggregate float differs')
    elif type(a) is not type(b) or a!=b:
        raise ValueError('Aggregate exact value differs')


def baskets(source,schemas,roles):
    for r in old.records(source/'baskets.csv',schemas['baskets.csv']):
        if r['role'] not in roles:
            continue
        yield c.Basket(p.item(r['visitorid']),old.number(r['session_start_ms']),old.number(r['query_ms']),
                       r['role'],old.number(r['basket_index']),old.array(r['items']))


def queries(source,schemas,parent):
    lo,hi=map(old.ms,parent['time_roles']['validation'])
    for r in old.records(source/'queries.csv',schemas['queries.csv']):
        if r['role']!='validation':
            continue
        v=p.item(r['visitorid']);s=old.number(r['session_start_ms']);t=old.number(r['query_ms']);nt=old.number(r['next_view_ms'])
        if not lo<=t<nt<hi or nt-t>1800000 or t+1800000>hi or s>t:
            raise ValueError('Validation clock/horizon mismatch')
        if any(r[k]!=x for k,x in [('status','labelled'),('next_role','validation'),('next_in_session','1'),('mature','1'),('cross_role','0')]):
            raise ValueError('Invalid accepted validation state')
        targets=old.array(r['target_items']);train=old.number(r['train_view_events'])
        if len(targets)!=old.number(r['target_count']) or p.activity(train)!=r['train_activity_slice']:
            raise ValueError('Target/activity mismatch')
        q=p.Query(v,s,t,'validation',targets,0,old.boolean(r['visitor_seen_before_fit']),train,
                  old.number(r['candidate_count']),old.number(r['reachable_target_count']),old.boolean(r['all_targets_reachable']))
        yield q,old.number(r['basket_index'])


def controls(folder):
    sources=[old.records(folder/name,old.HEADERS[name]) for name in ('ranked_queries.csv','query_metrics.csv','query_slices.csv')]
    sentinel=object()
    while True:
        values=[next(source,sentinel) for source in sources]
        if all(v is sentinel for v in values): return
        if any(v is sentinel for v in values): raise ValueError('P0 files have unequal rows')
        rank,metric,slices=values
        keys=[(r['visitorid'],old.number(r['session_start_ms']),old.number(r['query_ms']),r['role']) for r in values]
        if len(set(keys))!=1: raise ValueError('P0 file keys differ')
        yield rank,metric,slices


class PairFold:
    def __init__(self,cat):
        self.arms={a:p.Aggregate(cat) for a in ('P0','C1')}
        self.deltas={m:[] for m in p.METRICS}
    def add(self,q,pred,terms,reachable):
        for a in self.arms: self.arms[a].add(q,pred[a],terms[a],reachable)
        for m in self.deltas: self.deltas[m].append(terms['C1'][m]-terms['P0'][m])
    def result(self):
        arms={a:v.result() for a,v in self.arms.items()}
        n=arms['P0']['queries']
        delta={m:math.fsum(v)/n if n else None for m,v in self.deltas.items()}
        for m in ('visitor_macro_ndcg','catalog_coverage'):
            x,y=arms['C1']['metrics'][m],arms['P0']['metrics'][m]
            delta[m]=x-y if x is not None and y is not None else None
        return arms,{'queries':n,'visitors':arms['P0']['visitors'],'delta_metrics':delta}


def build(folder,source,baseline,schemas,policy,parent,expected_p0=None,watch=lambda:None):
    counts={}
    for row in old.records(baseline/'item_counts.csv',old.HEADERS['item_counts.csv']):
        i=p.item(row['itemid']);n=old.number(row['count'])
        if i in counts or n<1: raise ValueError('Invalid reused P0 count table')
        counts[i]=n
    start=old.ms(policy['comparison']['fit_start_inclusive_utc']);end=old.ms(policy['comparison']['fit_end_exclusive_utc'])
    cat=old.catalog(source,schemas)
    with ExitStack() as stack:
        handles={name:stack.enter_context((folder/name).open('x',encoding='utf-8',newline='')) for name in ARTIFACTS}
        def lineage(key,ids,n,o):
            handles['train_sessions.jsonl'].write(dump({'key':list(key),'items':ids,'baskets':n,'basket_memberships':o})+'\n')
        model=c.fit(baskets(source,schemas,('train',)),start,end,counts,lineage,watch)
        sw=csv.writer(handles['support.csv'],lineterminator='\n');sw.writerow(['itemid','support'])
        for i in sorted(model.support,key=int): sw.writerow([i,model.support[i]])
        pw=csv.writer(handles['pairs.csv'],lineterminator='\n');pw.writerow(['itemid_a','itemid_b','count'])
        for a,b in sorted(model.pairs,key=lambda x:(int(x[0]),int(x[1]))): pw.writerow([a,b,model.pairs[a,b]])
        handles['fit_audit.json'].write(dump(dict(model.audit,fit_id=model.fit_id))+'\n')
        ranker=c.Ranker(model,counts,cat)
        histories=c.Histories(baskets(source,schemas,('warmup','train','validation')))
        control=iter(controls(baseline));previous=None;records=[];roster=hashlib.sha256()
        main=PairFold(cat);conditional=PairFold(cat)
        groups={f:{g:PairFold(cat) for g in names} for f,names in p.GROUPS.items()}
        diagnostics={name:Counter() for name in ('history_size','supported_seeds','positive_evidence','fallback_reason','zero_fill_slots')}
        for raw,index in queries(source,schemas,parent):
            watch()
            if previous is not None and raw.key()<=previous: raise ValueError('Duplicate/unordered query roster')
            previous=raw.key()
            # The adapter uses current_size=0 until the exact basket is joined.
            history=histories.at(raw,index)
            q=replace(raw,current_size=len(histories.current.items))
            saved=next(control,None)
            if saved is None: raise ValueError('Missing P0 paired query')
            rank,metric,saved_slices=saved
            if (rank['visitorid'],old.number(rank['session_start_ms']),old.number(rank['query_ms']))!=q.key() or rank['role']!='validation':
                raise ValueError('P0/query roster not one-to-one')
            if rank['fit_id']!=policy['P0_identity']['fit_id']: raise ValueError('Wrong reused P0 fit')
            pred0={'ids':json.loads(rank['top10_items']),'candidate_count':old.number(rank['candidate_count'])}
            if pred0['candidate_count']!=cat.size(q.query_ms) or len(pred0['ids'])!=min(10,q.candidate_count) or len(set(pred0['ids']))!=len(pred0['ids']) or any(not cat.contains(i,q.query_ms) for i in pred0['ids']):
                raise ValueError('P0 candidate/list mismatch')
            terms0={k:float(metric[k]) for k in ('dcg','idcg',*p.METRICS)}
            terms0.update(target_count=old.number(metric['target_count']),hits=old.number(metric['hits']),first_hit_rank=old.number(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
            if any(not math.isfinite(v) for v in terms0.values() if type(v) is float): raise ValueError('Nonfinite P0 metric')
            pred1=ranker.rank(q.query_ms,history);terms1=p.metric_terms(pred1['ids'],q.targets)
            reachable=sum(cat.contains(i,q.query_ms) for i in q.targets)
            if q.candidate_count!=pred1['candidate_count'] or q.reachable_count!=reachable or q.all_reachable!=(reachable==len(q.targets)) or terms0['target_count']!=len(q.targets) or metric['reachable_target_count']!=str(reachable) or old.boolean(metric['all_targets_reachable'])!=q.all_reachable:
                raise ValueError('Paired full target/candidate denominator mismatch')
            memberships=p.slice_names(q,counts)
            if any(saved_slices[k]!=v for k,v in memberships.items()): raise ValueError('Paired slices changed')
            predictions={'P0':pred0,'C1':pred1};terms={'P0':terms0,'C1':terms1}
            main.add(q,predictions,terms,reachable)
            if q.all_reachable: conditional.add(q,predictions,terms,reachable)
            for family,g in memberships.items(): groups[family][g].add(q,predictions,terms,reachable)
            delta={m:terms1[m]-terms0[m] for m in p.METRICS}
            records.append((q.visitorid,delta['ndcg']))
            history_hash=hashlib.sha256(dump(list(history)).encode()).hexdigest()
            output={'key':list(q.key()),'history':list(history),'history_sha256':history_hash,'targets':list(q.targets),
                    'candidate_count':q.candidate_count,'reachable_targets':reachable,'predictions':predictions,
                    'terms':terms,'delta':delta,'slices':memberships}
            handles['queries.jsonl'].write(dump(output)+'\n');roster.update((dump(list(q.key()))+'\n').encode())
            diagnostics['history_size'][str(len(history))]+=1
            diagnostics['supported_seeds'][str(pred1['supported_seeds'])]+=1
            e=pred1['positive_candidates'];diagnostics['positive_evidence']['0' if not e else '1-9' if e<10 else 'at_least_10']+=1
            diagnostics['fallback_reason'][pred1['fallback_reason'] or 'positive_evidence']+=1
            diagnostics['zero_fill_slots'][str(pred1['zero_fill_slots'])]+=1
        if next(control,None) is not None: raise ValueError('Extra P0 query')
        arms,paired=main.result();conditional_arms,paired['conditional']=conditional.result()
        floor=max(50,(paired['queries']+99)//100);paired['slices']={}
        for a in arms: arms[a].update(conditional=conditional_arms[a],support_floor_queries=floor,slices={})
        for family,buckets in groups.items():
            paired['slices'][family]={}
            for a in arms: arms[a]['slices'][family]={}
            for g,fold in buckets.items():
                ga,gp=fold.result();n=gp['queries'];support='empty' if not n else 'descriptive_only' if n<floor else 'sufficient_query_count'
                gp['support']=support;paired['slices'][family][g]=gp
                for a in arms: ga[a]['support']=support;arms[a]['slices'][family][g]=ga[a]
        if expected_p0 is not None: close(arms['P0'],expected_p0)
        fixed=policy['fixed_validation'];actual=arms['C1']
        for key in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries','candidate_union_items','support_floor_queries'):
            if actual[key]!=fixed[key]: raise ValueError('Fixed validation denominator changed: '+key)
        for family,g,key in [('visitor_history','new','new_visitor_queries'),('current_basket','multiple','multi_item_current_queries'),('target_basket','multiple','multi_item_target_queries')]:
            if actual['slices'][family][g]['queries']!=fixed[key]: raise ValueError('Fixed slice changed')
        if {g:v['queries'] for g,v in actual['slices']['target_model'].items()}!=fixed['target_model_query_counts']: raise ValueError('Target support partitions changed')
        uncertainty=c.bootstrap(records,lambda value:handles['bootstrap.jsonl'].write(dump(value)+'\n'),watch)
        result={'arms':arms,'paired':paired,'diagnostics':{k:dict(v) for k,v in diagnostics.items()},
                'uncertainty':uncertainty,'roster_sha256':roster.hexdigest()}
        handles['aggregate.json'].write(dump(result)+'\n')
    return {'fit_audit':dict(model.audit,fit_id=model.fit_id),'aggregate':result}
