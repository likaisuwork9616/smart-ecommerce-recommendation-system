"""Independent SQL counts, full-order oracle and Decimal metrics/readback.

No imports from production P0, aggregate or CSV adapter modules.
"""
from bisect import bisect_left
import csv
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import math
import re
import sqlite3

METRICS=('ndcg','recall','hit_rate','mrr')
GROUPS={'visitor_history':('seen','new'),'current_basket':('single','multiple'),'target_basket':('single','multiple'),
        'train_activity':('0','1','2-5','6+'),'target_model':('all_positive','mixed','all_zero')}
FIELDS={
 'item_counts.csv':['itemid','count'],
 'ranked_queries.csv':['visitorid','session_start_ms','query_ms','role','fit_id','top10_items','top10_scores','candidate_count'],
 'query_metrics.csv':['visitorid','session_start_ms','query_ms','role','target_count','reachable_target_count','all_targets_reachable','hits','first_hit_rank','dcg','idcg','ndcg','recall','hit_rate','mrr'],
 'query_slices.csv':['visitorid','session_start_ms','query_ms','role','visitor_history','current_basket','target_basket','train_activity','target_model']}
FLOATS={'dcg','idcg','ndcg','recall','hit_rate','mrr'}


def ms(s):return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp())*1000


def num(s):
    if not isinstance(s,str) or re.fullmatch(r'(0|[1-9][0-9]*)',s,flags=re.ASCII) is None:raise ValueError('Oracle invalid numeric source')
    return int(s)


def read_rows(path,header):
    with path.open(encoding='utf-8',newline='') as f:
        r=csv.DictReader(f)
        if r.fieldnames!=header:raise ValueError('Oracle source schema differs')
        for row in r:
            if None in row or any(v is None for v in row.values()):raise ValueError('Oracle record width differs')
            yield row


def close(actual,expected,where='root'):
    if isinstance(expected,dict):
        if not isinstance(actual,dict) or set(actual)!=set(expected):raise ValueError('Oracle JSON keys differ: '+where)
        for k in expected:close(actual[k],expected[k],where+'.'+k)
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(actual)!=len(expected):raise ValueError('Oracle list differs: '+where)
        for j,v in enumerate(expected):close(actual[j],v,where+'.'+str(j))
    elif type(expected) is float:
        if type(actual) not in (float,int) or not math.isfinite(actual) or not math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-12):raise ValueError('Oracle float differs: '+where)
    elif type(actual) is not type(expected) or actual!=expected:raise ValueError('Oracle exact scalar differs: '+where)


def full_order(counts,catalog,t):
    eligible=[i for i,first in catalog.items() if first<t]
    return sorted(eligible,key=lambda i:(-counts.get(i,0),num(i)))[:10],len(eligible)


@lru_cache(maxsize=1)
def discounts():
    with localcontext() as context:
        context.prec=50
        return {j:Decimal(2).ln()/Decimal(j+1).ln() for j in range(1,11)}


def terms(ids,targets):
    if not targets or len(targets)!=len(set(targets)):raise ValueError('Oracle invalid full target set')
    if len(ids)>10 or len(ids)!=len(set(ids)):raise ValueError('Oracle invalid predictions')
    truth=set(targets);places=[j for j,i in enumerate(ids,1) if i in truth]
    with localcontext() as context:
        context.prec=50
        discount=discounts()
        dcg=sum((discount[j] for j in places),Decimal(0));idcg=sum((discount[j] for j in range(1,min(10,len(truth))+1)),Decimal(0))
        recall=Fraction(len(places),len(truth));mrr=Fraction(1,places[0]) if places else Fraction(0)
        exact={'ndcg':dcg/idcg,'recall':Decimal(recall.numerator)/Decimal(recall.denominator),
               'hit_rate':Decimal(int(bool(places))),'mrr':Decimal(mrr.numerator)/Decimal(mrr.denominator)}
        floats={k:float(v) for k,v in exact.items()}
        return dict(target_count=len(truth),hits=len(places),first_hit_rank=places[0] if places else None,dcg=float(dcg),idcg=float(idcg),**floats),exact


class Fold:
    def __init__(self,catalog):
        self.catalog=catalog;self.n=0;self.v={};self.total={m:Decimal(0) for m in METRICS};self.target=0;self.reach=0;self.complete=0;self.rec=set();self.latest=None
    def add(self,q,ids,values,reachable):
        self.n+=1;self.target+=len(q['targets']);self.reach+=reachable;self.complete+=int(reachable==len(q['targets']))
        self.rec.update(ids);self.latest=q['t'] if self.latest is None else max(self.latest,q['t'])
        old_n,old_sum=self.v.get(q['v'],(0,Decimal(0)));self.v[q['v']]=(old_n+1,old_sum+values['ndcg'])
        for m in METRICS:self.total[m]+=values[m]
    def result(self):
        union=sum(t<self.latest for t in self.catalog.values()) if self.latest is not None else 0
        values={m:float(self.total[m]/self.n) if self.n else None for m in METRICS}
        values['visitor_macro_ndcg']=float(sum((s/n for n,s in self.v.values()),Decimal(0))/len(self.v)) if self.v else None
        values['catalog_coverage']=float(Fraction(len(self.rec),union)) if union else None
        return {'queries':self.n,'visitors':len(self.v),'target_occurrences':self.target,'reachable_target_occurrences':self.reach,
                'all_targets_reachable_queries':self.complete,'recommended_unique_items':len(self.rec),'candidate_union_items':union,
                'metrics':values,'undefined_reason':'zero_queries' if not self.n else 'zero_catalog_union' if not union else None}


class Readback:
    def __init__(self,folder):
        self.handles={};self.readers={};self.n={name:0 for name in FIELDS}
        for name,header in FIELDS.items():
            f=(folder/name).open(encoding='utf-8',newline='');self.handles[name]=f;r=csv.reader(f)
            if next(r,None)!=header:raise ValueError('Oracle output schema differs: '+name)
            self.readers[name]=r
    def row(self,name,values):
        actual=next(self.readers[name],None)
        if actual is None or len(actual)!=len(values):raise ValueError('Oracle missing/width record: '+name)
        for col,a,e in zip(FIELDS[name],actual,values):
            if e is None:ok=a==''
            elif col in FLOATS:
                try:ok=math.isfinite(float(a)) and math.isclose(float(a),e,rel_tol=1e-12,abs_tol=1e-12)
                except ValueError:ok=False
            else:
                expected=json.dumps(e,ensure_ascii=False,separators=(',',':')) if isinstance(e,(list,tuple)) else ('1' if e else '0') if type(e) is bool else str(e)
                ok=a==expected
            if not ok:raise ValueError(f'Oracle cell mismatch {name}, row {self.n[name]+1}, column {col}; values remain private')
        self.n[name]+=1
    def finish(self):
        for name,r in self.readers.items():
            if next(r,None) is not None:raise ValueError('Oracle extra output record: '+name)
        return {name:{'rows':n,'cells':n*len(FIELDS[name])} for name,n in self.n.items()}
    def close(self):
        for f in self.handles.values():f.close()


def verify(folder,source,schemas,policy,parent):
    readback=Readback(folder);db=sqlite3.connect(':memory:');db.execute('PRAGMA temp_store=MEMORY')
    fit=policy['algorithm']['development_fit'];start,end=map(ms,(fit['start_inclusive_utc'],fit['end_exclusive_utc']))
    val_start,val_end=map(ms,parent['time_roles']['validation'])
    try:
        db.execute('CREATE TABLE views(i TEXT)');seen=0;other_role=0;other_event=0;batch=[]
        for r in read_rows(source/'qualified_events.csv',schemas['qualified_events.csv']):
            seen+=1;t=num(r['timestamp'])
            if r['role']!='train':other_role+=1;continue
            if not start<=t<end or r['event'] not in ('view','addtocart','transaction'):raise ValueError('Oracle invalid fit role/time/type')
            if r['event']!='view':other_event+=1;continue
            num(r['itemid']);batch.append((r['itemid'],))
            if len(batch)>=20000:db.executemany('INSERT INTO views VALUES(?)',batch);batch.clear()
        db.executemany('INSERT INTO views VALUES(?)',batch)
        counts=dict(db.execute('SELECT i,COUNT(*) FROM views GROUP BY i'))
        ordered=sorted(counts.items(),key=lambda r:num(r[0]))
        identity={'algorithm':'P0_global_canonical_view_count','start_ms':start,'end_ms':end,'roles':['train'],'counts':ordered}
        fit_id=hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        fit_audit={'source_rows':seen,'counted_view_rows':sum(counts.values()),'excluded_other_role_rows':other_role,'excluded_other_event_rows':other_event,
                   'positive_items':len(counts),'start_ms':start,'end_ms':end,'primary_fits':1,'fit_roles':['train'],'all_zero_fit':not bool(counts),'fit_id':fit_id}
        close(json.loads((folder/'fit_audit.json').read_text(encoding='utf-8')),fit_audit)
        for i,n in ordered:readback.row('item_counts.csv',[i,n])
        catalog={}
        for r in read_rows(source/'catalog.csv',schemas['catalog.csv']):
            num(r['itemid']);t=num(r['first_view_ms'])
            if r['itemid'] in catalog:raise ValueError('Oracle duplicate catalog ID')
            catalog[r['itemid']]=t
        if any(i not in catalog for i in counts):raise ValueError('Oracle fit item absent from catalog')
        universal=len(counts)>=10 and all(catalog[i]<val_start for i in counts)
        static=sorted(counts,key=lambda i:(-counts[i],num(i)))[:10] if universal else None
        sorted_first=sorted(catalog.values())
        db.execute('CREATE TABLE baskets(v TEXT,s INTEGER,t INTEGER,n INTEGER,PRIMARY KEY(v,s,t))')
        batch=[]
        for r in read_rows(source/'baskets.csv',schemas['baskets.csv']):
            if r['role']!='validation':continue
            items=json.loads(r['items'])
            if not isinstance(items,list) or not items or len(items)!=len(set(items)):raise ValueError('Oracle invalid current basket')
            for i in items:num(i)
            batch.append((r['visitorid'],num(r['session_start_ms']),num(r['query_ms']),len(items)))
            if len(batch)>=20000:db.executemany('INSERT INTO baskets VALUES(?,?,?,?)',batch);batch.clear()
        db.executemany('INSERT INTO baskets VALUES(?,?,?,?)',batch)
        main=Fold(catalog);conditional=Fold(catalog);groups={f:{g:Fold(catalog) for g in names} for f,names in GROUPS.items()};previous=None
        for r in read_rows(source/'queries.csv',schemas['queries.csv']):
            if r['role']!='validation':continue
            v=r['visitorid'];num(v);s=num(r['session_start_ms']);t=num(r['query_ms']);nt=num(r['next_view_ms']);key=(v,s,t)
            if previous is not None and key<=previous:raise ValueError('Oracle duplicate/unordered query')
            previous=key
            if not (val_start<=t<val_end and s<=t<nt<val_end and nt-t<=1800000 and t+1800000<=val_end):raise ValueError('Oracle query clock mismatch')
            if any(r[k]!=value for k,value in [('status','labelled'),('next_role','validation'),('next_in_session','1'),('mature','1'),('cross_role','0')]):raise ValueError('Oracle query state differs')
            target=json.loads(r['target_items'])
            if not isinstance(target,list) or not target or len(target)!=len(set(target)) or len(target)!=num(r['target_count']):raise ValueError('Oracle target differs')
            for i in target:num(i)
            found=db.execute('SELECT n FROM baskets WHERE v=? AND s=? AND t=?',key).fetchone()
            if found is None:raise ValueError('Oracle query basket missing')
            if universal:ids=list(static);candidate_n=bisect_left(sorted_first,t)
            else:ids,candidate_n=full_order(counts,catalog,t)
            reachable=sum(i in catalog and catalog[i]<t for i in target)
            if candidate_n!=num(r['candidate_count']) or reachable!=num(r['reachable_target_count']) or r['all_targets_reachable']!=str(int(reachable==len(target))):raise ValueError('Oracle causal denominator differs')
            if r['visitor_seen_before_fit'] not in ('0','1'):raise ValueError('Oracle visitor flag malformed')
            train_n=num(r['train_view_events']);bucket='0' if train_n==0 else '1' if train_n==1 else '2-5' if train_n<6 else '6+'
            if bucket!=r['train_activity_slice']:raise ValueError('Oracle activity differs')
            positives=sum(counts.get(i,0)>0 for i in target)
            memberships={'visitor_history':'seen' if r['visitor_seen_before_fit']=='1' else 'new','current_basket':'single' if found[0]==1 else 'multiple',
                'target_basket':'single' if len(target)==1 else 'multiple','train_activity':bucket,
                'target_model':'all_positive' if positives==len(target) else 'all_zero' if positives==0 else 'mixed'}
            values,exact=terms(ids,target);q={'v':v,'s':s,'t':t,'targets':target}
            main.add(q,ids,exact,reachable)
            if reachable==len(target):conditional.add(q,ids,exact,reachable)
            for family,g in memberships.items():groups[family][g].add(q,ids,exact,reachable)
            outkey=[v,s,t,'validation']
            readback.row('ranked_queries.csv',[*outkey,fit_id,ids,[counts.get(i,0) for i in ids],candidate_n])
            readback.row('query_metrics.csv',[*outkey,len(target),reachable,reachable==len(target),*[values[k] for k in ('hits','first_hit_rank','dcg','idcg','ndcg','recall','hit_rate','mrr')]])
            readback.row('query_slices.csv',[*outkey,*memberships.values()])
        aggregate=main.result();floor=max(50,(aggregate['queries']+99)//100);aggregate['conditional']=conditional.result();aggregate['support_floor_queries']=floor;aggregate['slices']={}
        for family,buckets in groups.items():
            aggregate['slices'][family]={}
            for g,fold in buckets.items():
                a=fold.result();a['support']='empty' if not a['queries'] else 'descriptive_only' if a['queries']<floor else 'sufficient_query_count';aggregate['slices'][family][g]=a
        expected=policy['fixed_denominators_from_accepted_build']['validation']
        for k in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries'):
            if aggregate[k]!=expected[k]:raise ValueError('Oracle fixed denominator mismatch: '+k)
        if aggregate['support_floor_queries']!=expected['support_floor_queries']:raise ValueError('Oracle support floor mismatch')
        for f,g,k in [('visitor_history','new','new_visitor_queries'),('current_basket','multiple','multi_item_current_basket_queries'),('target_basket','multiple','multi_item_target_basket_queries')]:
            if aggregate['slices'][f][g]['queries']!=expected[k]:raise ValueError('Oracle fixed slice differs')
        close(json.loads((folder/'aggregate.json').read_text(encoding='utf-8')),aggregate)
        files=readback.finish()
        return {'status':'independent_SQL_Decimal_full_readback_passed','files':files,'rows':sum(r['rows'] for r in files.values()),
                'cells':sum(r['cells'] for r in files.values()),'independent_count_audits':1,
                'ranking_oracle':{'universal_positive_order_proved':universal,'positive_fit_items':len(counts),'proof_cutoff_ms':val_start,
                                  'basis':'all positive fit IDs precede every validation query and at least 10 positive IDs; otherwise full-catalog sort per query'},
                'aggregate':aggregate}
    finally:readback.close();db.close()
