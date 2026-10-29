"""Accepted CSV adapters and exclusive development artifact writer; no test path."""
from __future__ import annotations
import csv
from datetime import datetime
import json
from pathlib import Path

from scripts import retailrocket_popularity as p

HEADERS={
 'item_counts.csv':['itemid','count'],
 'ranked_queries.csv':['visitorid','session_start_ms','query_ms','role','fit_id','top10_items','top10_scores','candidate_count'],
 'query_metrics.csv':['visitorid','session_start_ms','query_ms','role','target_count','reachable_target_count','all_targets_reachable','hits','first_hit_rank','dcg','idcg','ndcg','recall','hit_rate','mrr'],
 'query_slices.csv':['visitorid','session_start_ms','query_ms','role','visitor_history','current_basket','target_basket','train_activity','target_model'],
}
FLOAT_COLUMNS={'dcg','idcg','ndcg','recall','hit_rate','mrr'}


def number(s):
    p.item(s);return int(s)


def boolean(s):
    if s not in ('0','1'):raise ValueError('Expected explicit boolean')
    return s=='1'


def array(s):
    value=json.loads(s)
    if not isinstance(value,list) or not value or any(not isinstance(i,str) for i in value):raise ValueError('Expected nonempty ID array')
    for i in value:p.item(i)
    if len(value)!=len(set(value)):raise ValueError('Duplicate basket/target ID')
    return tuple(value)


def records(path,header):
    with path.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=header:raise ValueError('Unexpected accepted CSV schema: '+path.name)
        for row in reader:
            if None in row or any(v is None for v in row.values()):raise ValueError('CSV width mismatch: '+path.name)
            yield row


def ms(s):return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp())*1000


def events(folder,schemas):
    for row in records(folder/'qualified_events.csv',schemas['qualified_events.csv']):
        yield {'timestamp':number(row['timestamp']),'role':row['role'],'event':row['event'],'itemid':row['itemid']}


def catalog(folder,schemas):
    return p.Catalog((row['itemid'],number(row['first_view_ms'])) for row in records(folder/'catalog.csv',schemas['catalog.csv']))


def queries(folder,schemas,parent,role='validation'):
    if role!='validation':raise ValueError('Only validation may be opened by development loader')
    start,end=map(ms,parent['time_roles'][role])
    def baskets():
        previous=None
        for row in records(folder/'baskets.csv',schemas['baskets.csv']):
            if row['role']!=role:continue
            key=(p.item(row['visitorid']),number(row['session_start_ms']),number(row['query_ms']))
            if previous is not None and key<=previous:raise ValueError('Unordered or duplicate basket key')
            previous=key
            yield key,len(array(row['items']))
    source=iter(baskets());current=next(source,None)
    for row in records(folder/'queries.csv',schemas['queries.csv']):
        if row['role']!=role:continue
        v=p.item(row['visitorid']);s=number(row['session_start_ms']);t=number(row['query_ms']);key=(v,s,t)
        nt=number(row['next_view_ms'])
        if row['status']!='labelled' or row['next_role']!=role or not boolean(row['next_in_session']) or not boolean(row['mature']) or boolean(row['cross_role']):raise ValueError('Invalid labelled query state')
        if not(start<=t<end and t<nt<end and nt-t<=1800000 and t+1800000<=end and s<=t):raise ValueError('Invalid query temporal boundary')
        while current is not None and current[0]<key:current=next(source,None)
        if current is None or current[0]!=key:raise ValueError('Query missing exact current basket')
        targets=array(row['target_items'])
        if len(targets)!=number(row['target_count']):raise ValueError('Target denominator mismatch')
        train_n=number(row['train_view_events'])
        if p.activity(train_n)!=row['train_activity_slice']:raise ValueError('Training-only activity bucket differs')
        yield p.Query(v,s,t,role,targets,current[1],boolean(row['visitor_seen_before_fit']),train_n,
                      number(row['candidate_count']),number(row['reachable_target_count']),boolean(row['all_targets_reachable']))


def cell(value):
    if value is None:return ''
    if type(value) is bool:return '1' if value else '0'
    if isinstance(value,(list,tuple)):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return str(value)


def artifact_rows(q,prediction,terms,memberships):
    key=[q.visitorid,q.session_start_ms,q.query_ms,q.role]
    return {
        'ranked_queries.csv':[*key,prediction['fit_id'],prediction['ids'],prediction['scores'],prediction['candidate_count']],
        'query_metrics.csv':[*key,len(q.targets),q.reachable_count,q.all_reachable,*[terms[k] for k in ('hits','first_hit_rank','dcg','idcg','ndcg','recall','hit_rate','mrr')]],
        'query_slices.csv':[*key,*[memberships[k] for k in p.GROUPS]],
    }


def build_development(folder,source_folder,schemas,policy,parent):
    """Used on tiny synthetic corpora now; real calls require frozen CLI guard."""
    opened={};writers={};counts={name:0 for name in HEADERS}
    try:
        for name,header in HEADERS.items():
            f=(folder/name).open('x',encoding='utf-8',newline='');opened[name]=f
            w=csv.writer(f,lineterminator='\n');w.writerow(header);writers[name]=w
        a=policy['algorithm']['development_fit'];start=ms(a['start_inclusive_utc']);end=ms(a['end_exclusive_utc'])
        model=p.fit_counts(events(source_folder,schemas),start,end)
        for i,n in model.counts.items():writers['item_counts.csv'].writerow([i,n]);counts['item_counts.csv']+=1
        cat=catalog(source_folder,schemas);ranker=p.Ranker(model,cat)
        def emit(q,prediction,terms,memberships):
            for name,row in artifact_rows(q,prediction,terms,memberships).items():
                if len(row)!=len(HEADERS[name]):raise ValueError('Artifact schema width differs')
                writers[name].writerow([cell(v) for v in row]);counts[name]+=1
        result=p.evaluate(ranker,queries(source_folder,schemas,parent),expected=policy['fixed_denominators_from_accepted_build']['validation'],emit=emit)
        with (folder/'fit_audit.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(dict(model.audit,fit_id=model.fit_id),f,indent=2);f.write('\n')
        with (folder/'aggregate.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
        return {'aggregate':result,'fit_audit':dict(model.audit,fit_id=model.fit_id),'files':counts}
    finally:
        for f in opened.values():f.close()
