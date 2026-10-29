"""P0 integer view counts, exact causal top-10 and complete-target evaluation."""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType

ID=re.compile(r'^(0|[1-9][0-9]*)$',re.ASCII)
K=10
METRICS=('ndcg','recall','hit_rate','mrr')
GROUPS={'visitor_history':('seen','new'),'current_basket':('single','multiple'),
        'target_basket':('single','multiple'),'train_activity':('0','1','2-5','6+'),
        'target_model':('all_positive','mixed','all_zero')}


def item(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise ValueError('Noncanonical anonymous ID')
    return value


def integer(value):
    if type(value) is not int or value<0:raise ValueError('Expected nonnegative integer')
    return value


def activity(n):
    integer(n)
    return '0' if n==0 else '1' if n==1 else '2-5' if n<=5 else '6+'


@dataclass(frozen=True)
class Model:
    counts: object
    fit_id: str
    audit: object


def fit_counts(events,start_ms,end_ms,roles=('train',)):
    integer(start_ms);integer(end_ms)
    if start_ms>=end_ms or tuple(roles)!=('train',):raise ValueError('Development fit accepts train only')
    counts=Counter();seen=0;included=0;excluded_role=0;excluded_type=0
    for row in events:
        seen+=1
        if row['role'] not in roles:excluded_role+=1;continue
        t=integer(row['timestamp'])
        if not start_ms<=t<end_ms:raise ValueError('Selected role/time mismatch')
        if row['event'] not in ('view','addtocart','transaction'):raise ValueError('Unknown fit-source event type')
        if row['event']!='view':excluded_type+=1;continue
        counts[item(row['itemid'])]+=1;included+=1
    values=tuple(sorted(counts.items(),key=lambda r:int(r[0])))
    identity={'algorithm':'P0_global_canonical_view_count','start_ms':start_ms,'end_ms':end_ms,'roles':list(roles),'counts':values}
    digest=hashlib.sha256(json.dumps(identity,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    audit={'source_rows':seen,'counted_view_rows':included,'excluded_other_role_rows':excluded_role,
           'excluded_other_event_rows':excluded_type,'positive_items':len(counts),'start_ms':start_ms,'end_ms':end_ms,
           'primary_fits':1,'fit_roles':list(roles),'all_zero_fit':not bool(counts)}
    return Model(MappingProxyType(dict(values)),digest,MappingProxyType(audit))


class Catalog:
    def __init__(self,rows):
        first={}
        for i,t in rows:
            item(i);integer(t)
            if i in first:raise ValueError('Duplicate catalog item')
            first[i]=t
        self.first=MappingProxyType(first)
        self.times=tuple(sorted(first.values()))
        self.numeric=tuple(sorted(first,key=int))
    def size(self,t):return bisect_left(self.times,integer(t))
    def contains(self,i,t):return i in self.first and self.first[i]<t


class Ranker:
    """Cannot receive targets, visitor features or future query metadata."""
    def __init__(self,model,catalog):
        self.model=model;self.catalog=catalog
        for i,n in model.counts.items():
            item(i)
            if type(n) is not int or n<=0 or i not in catalog.first:raise ValueError('Invalid fitted item/catalog identity')
        self.positive=tuple(sorted(model.counts,key=lambda i:(-model.counts[i],int(i))))
        self.zero=tuple(i for i in catalog.numeric if i not in model.counts)
    def rank(self,query_ms):
        n=self.catalog.size(query_ms);ids=self._select(query_ms,n)
        result={'fit_id':self.model.fit_id,'ids':ids,'scores':[self.model.counts.get(i,0) for i in ids],'candidate_count':n}
        self.validate_prediction(query_ms,result)
        return result
    def _select(self,query_ms,n):
        wanted=min(K,n);ids=[]
        if wanted:
            for i in self.positive:
                if self.catalog.contains(i,query_ms):ids.append(i)
                if len(ids)==wanted:break
            if len(ids)<wanted:
                for i in self.zero:
                    if self.catalog.contains(i,query_ms):ids.append(i)
                    if len(ids)==wanted:break
        return ids
    def validate_prediction(self,t,prediction):
        ids=prediction['ids'];scores=prediction['scores']
        if prediction['fit_id']!=self.model.fit_id or prediction['candidate_count']!=self.catalog.size(t):raise ValueError('Wrong fit or candidate identity')
        if len(ids)!=min(K,self.catalog.size(t)) or len(ids)!=len(set(ids)) or len(scores)!=len(ids):raise ValueError('Invalid recommendation length/duplicates')
        if any(not self.catalog.contains(item(i),t) for i in ids):raise ValueError('Noncausal candidate')
        if any(type(n) is not int or n<0 or n!=self.model.counts.get(i,0) for i,n in zip(ids,scores)):raise ValueError('Wrong/noninteger score')
        if ids!=sorted(ids,key=lambda i:(-self.model.counts.get(i,0),int(i))):raise ValueError('Invalid recommendation order')
        if ids!=self._select(t,self.catalog.size(t)):raise ValueError('Not exact complete-catalog top10')


def metric_terms(predicted,targets):
    if not targets or len(targets)!=len(set(targets)):raise ValueError('Targets must be unique and nonempty')
    if len(predicted)>K or len(predicted)!=len(set(predicted)):raise ValueError('Invalid top10 IDs')
    for i in list(targets)+list(predicted):item(i)
    truth=set(targets);ranks=[r for r,i in enumerate(predicted,1) if i in truth]
    dcg=math.fsum(1/math.log2(r+1) for r in ranks)
    idcg=math.fsum(1/math.log2(r+1) for r in range(1,min(K,len(targets))+1))
    first=ranks[0] if ranks else None
    return {'target_count':len(targets),'hits':len(ranks),'first_hit_rank':first,'dcg':dcg,'idcg':idcg,
            'ndcg':dcg/idcg,'recall':len(ranks)/len(targets),'hit_rate':float(bool(ranks)),'mrr':1/first if first else 0.0}


@dataclass(frozen=True)
class Query:
    visitorid: str
    session_start_ms: int
    query_ms: int
    role: str
    targets: tuple
    current_size: int
    visitor_seen: bool
    train_views: int
    candidate_count: int
    reachable_count: int
    all_reachable: bool
    def key(self):return (self.visitorid,self.session_start_ms,self.query_ms)


class Sum:
    def __init__(self):self.total=0.0;self.c=0.0
    def add(self,value):
        if not math.isfinite(value):raise ValueError('Nonfinite metric')
        updated=self.total+value
        self.c+=(self.total-updated)+value if abs(self.total)>=abs(value) else (value-updated)+self.total
        self.total=updated
    def value(self):return self.total+self.c


class Aggregate:
    def __init__(self,catalog):
        self.catalog=catalog;self.n=0;self.visitors={};self.sums={m:Sum() for m in METRICS}
        self.targets=0;self.reachable=0;self.all_reachable=0;self.recommended=set();self.max_t=None
    def add(self,q,prediction,terms,reachable):
        self.n+=1;self.targets+=len(q.targets);self.reachable+=reachable;self.all_reachable+=int(reachable==len(q.targets))
        self.max_t=q.query_ms if self.max_t is None else max(self.max_t,q.query_ms)
        self.recommended.update(prediction['ids'])
        n,s=self.visitors.setdefault(q.visitorid,[0,Sum()]);self.visitors[q.visitorid][0]=n+1;s.add(terms['ndcg'])
        for m in METRICS:self.sums[m].add(terms[m])
    def result(self):
        union=self.catalog.size(self.max_t) if self.max_t is not None else 0
        values={m:self.sums[m].value()/self.n if self.n else None for m in METRICS}
        values.update(visitor_macro_ndcg=math.fsum(s.value()/n for n,s in self.visitors.values())/len(self.visitors) if self.visitors else None,
                      catalog_coverage=len(self.recommended)/union if union else None)
        return {'queries':self.n,'visitors':len(self.visitors),'target_occurrences':self.targets,'reachable_target_occurrences':self.reachable,
                'all_targets_reachable_queries':self.all_reachable,'recommended_unique_items':len(self.recommended),'candidate_union_items':union,
                'metrics':values,'undefined_reason':'zero_queries' if not self.n else 'zero_catalog_union' if not union else None}


def slice_names(q,counts):
    known=sum(counts.get(i,0)>0 for i in q.targets)
    return {'visitor_history':'seen' if q.visitor_seen else 'new','current_basket':'multiple' if q.current_size>1 else 'single',
            'target_basket':'multiple' if len(q.targets)>1 else 'single','train_activity':activity(q.train_views),
            'target_model':'all_positive' if known==len(q.targets) else 'all_zero' if known==0 else 'mixed'}


def evaluate(ranker,queries,role='validation',expected=None,emit=None):
    if role!='validation':raise ValueError('Reserved test and training scoring are locked in this development entry')
    main=Aggregate(ranker.catalog);conditional=Aggregate(ranker.catalog)
    groups={family:{g:Aggregate(ranker.catalog) for g in names} for family,names in GROUPS.items()}
    previous=None
    for q in queries:
        item(q.visitorid);integer(q.session_start_ms);integer(q.query_ms);integer(q.current_size);integer(q.train_views);integer(q.candidate_count);integer(q.reachable_count)
        if q.role!=role or q.current_size<1 or q.session_start_ms>q.query_ms or type(q.visitor_seen) is not bool or type(q.all_reachable) is not bool:raise ValueError('Invalid query context/role')
        if previous is not None and q.key()<=previous:raise ValueError('Query keys duplicated or unordered')
        previous=q.key()
        prediction=ranker.rank(q.query_ms);terms=metric_terms(prediction['ids'],q.targets)
        reachable=sum(ranker.catalog.contains(i,q.query_ms) for i in q.targets)
        if q.candidate_count!=prediction['candidate_count'] or q.reachable_count!=reachable or q.all_reachable!=(reachable==len(q.targets)):
            raise ValueError('Accepted query denominator/catalog differs')
        main.add(q,prediction,terms,reachable)
        if reachable==len(q.targets):conditional.add(q,prediction,terms,reachable)
        memberships=slice_names(q,ranker.model.counts)
        for family,g in memberships.items():groups[family][g].add(q,prediction,terms,reachable)
        if emit is not None:emit(q,prediction,terms,memberships)
    result=main.result();floor=max(50,(result['queries']+99)//100)
    result['conditional']=conditional.result();result['support_floor_queries']=floor;result['slices']={}
    for family,buckets in groups.items():
        result['slices'][family]={}
        for g,agg in buckets.items():
            value=agg.result();n=value['queries'];value['support']='empty' if not n else 'descriptive_only' if n<floor else 'sufficient_query_count'
            result['slices'][family][g]=value
    if expected is not None:
        for key in ('queries','visitors','target_occurrences','reachable_target_occurrences','all_targets_reachable_queries'):
            if result[key]!=expected[key]:raise ValueError('Fixed denominator mismatch: '+key)
        if result['support_floor_queries']!=expected['support_floor_queries']:raise ValueError('Support floor drift')
        comparisons=[('visitor_history','new','new_visitor_queries'),('current_basket','multiple','multi_item_current_basket_queries'),('target_basket','multiple','multi_item_target_basket_queries')]
        for family,g,key in comparisons:
            if result['slices'][family][g]['queries']!=expected[key]:raise ValueError('Slice denominator drift: '+key)
    return result
