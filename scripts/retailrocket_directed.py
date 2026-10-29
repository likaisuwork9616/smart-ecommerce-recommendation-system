"""Exact D1 directed adjacent-basket association and paired cluster resampling."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
from types import MappingProxyType
import numpy as np

from scripts import retailrocket_popularity as p
from scripts.retailrocket_cooccurrence import Basket, Histories


def identity(support, edges, start, end):
    h = hashlib.sha256(f'D1_binary_session_directed_adjacent_association_v1\n{start},{end}\n'.encode())
    for i in sorted(support, key=int): h.update(f'S,{i},{support[i]}\n'.encode())
    for a, b in sorted(edges, key=lambda x: (int(x[0]), int(x[1]))):
        h.update(f'D,{a},{b},{edges[a,b]}\n'.encode())
    return h.hexdigest()


@dataclass(frozen=True)
class Model:
    support: object
    edges: object
    fit_id: str
    audit: object


def train_sessions(baskets, start, end, watch=lambda: None):
    """Only original train adjacency; gaps never become synthetic transitions."""
    key = previous_key = previous_basket = None
    members, edges = set(), set()
    n = occurrences = adjacent = raw = 0
    for b in baskets:
        if b.role != 'train': continue
        watch()
        p.item(b.visitor)
        if (type(b.time) is not int or type(b.session) is not int or type(b.index) is not int
                or not start <= b.time < end or not 0 <= b.session <= b.time or b.index < 1):
            raise ValueError('Train role/time/index mismatch')
        if previous_key is not None and b.key() <= previous_key:
            raise ValueError('Duplicate/unordered train basket')
        previous_key = b.key()
        current = b.key()[:2]
        if key is not None and current != key:
            yield key, members, edges, n, occurrences, adjacent, raw
            members, edges = set(), set()
            n = occurrences = adjacent = raw = 0
            previous_basket = None
        key = current
        if not b.items or len(b.items) != len(set(b.items)):
            raise ValueError('Empty/duplicate basket membership')
        for i in b.items: p.item(i)
        if previous_basket is not None:
            if b.index <= previous_basket.index: raise ValueError('Train basket indices not increasing')
            if b.index == previous_basket.index + 1 and 0 < b.time-previous_basket.time <= 1800000:
                adjacent += 1
                for a in previous_basket.items:
                    for z in b.items:
                        if a == z: continue
                        edges.add((a,z)); raw += 1
                        if raw % 50000 == 0: watch()
        members.update(b.items); n += 1; occurrences += len(b.items)
        previous_basket = b
    if key is not None: yield key, members, edges, n, occurrences, adjacent, raw


def fit(baskets, start, end, support, c1_pairs, p0_counts, emit_session=None, watch=lambda: None):
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('Invalid training clock')
    support = dict(support)
    if set(support) != set(p0_counts): raise ValueError('Shared C1 support/P0 positive keys differ')
    for i,n in support.items():
        p.item(i)
        if type(n) is not int or n < 1 or type(p0_counts[i]) is not int or n > p0_counts[i]:
            raise ValueError('Invalid shared support/P0 count bound')
    for (a,b),n in c1_pairs.items():
        p.item(a);p.item(b)
        if int(a) >= int(b) or a not in support or b not in support or type(n) is not int or not 0 < n <= min(support[a],support[b]):
            raise ValueError('Invalid frozen C1 pair')
    counts = Counter()
    sessions = singleton = basket_n = occurrences = memberships = adjacent = raw = distinct = 0
    for key, members, edges, n, o, a, r in train_sessions(baskets,start,end,watch):
        if not members <= support.keys(): raise ValueError('Train item absent from shared support')
        sessions += 1; singleton += len(members) == 1; basket_n += n; occurrences += o
        memberships += len(members); adjacent += a; raw += r; distinct += len(edges)
        counts.update(edges)
        if emit_session:
            emit_session({'key':list(key),'items':sorted(members,key=int),'baskets':n,'basket_memberships':o,
                          'adjacent_pairs':a,'raw_directed_emissions':r,
                          'edges':[list(e) for e in sorted(edges,key=lambda e:(int(e[0]),int(e[1])))]})
    if memberships != sum(support.values()): raise ValueError('Shared support/session membership sum mismatch')
    for (a,b),n in counts.items():
        pair=(a,b) if int(a)<int(b) else (b,a)
        if a == b or not 0 < n <= c1_pairs.get(pair,0) <= min(support[a],support[b]):
            raise ValueError('D1/C1 edge upper bound failed')
    if sum(counts.values()) != distinct or distinct > 2*sum(c1_pairs.values()) or len(counts)>2*len(c1_pairs):
        raise ValueError('Directed edge conservation/bound failed')
    audit={'train_sessions':sessions,'singleton_sessions':singleton,'train_baskets':basket_n,
           'basket_item_memberships':occurrences,'distinct_session_item_memberships':memberships,
           'eligible_adjacent_basket_pairs':adjacent,'raw_directed_emissions':raw,
           'distinct_session_directed_edges':distinct,'unique_directed_edges':len(counts),
           'positive_support_items':len(support),'start_ms':start,'end_ms':end}
    return Model(MappingProxyType(support),MappingProxyType(dict(counts)),
                 identity(support,counts,start,end),MappingProxyType(audit))


class Ranker:
    def __init__(self, model, p0_counts, catalog):
        self.model,self.p0,self.catalog=model,dict(p0_counts),catalog
        if set(model.support)!=set(self.p0) or any(i not in catalog.first for i in model.support):
            raise ValueError('Ranker support/catalog identity differs')
        self.neighbors=defaultdict(list);incoming=set()
        for i,n in model.support.items():
            p.item(i)
            if type(n) is not int or n<1 or type(self.p0[i]) is not int or self.p0[i]<n:
                raise ValueError('Invalid ranker support/P0 counts')
        for (a,b),n in model.edges.items():
            if a==b or a not in model.support or b not in model.support or type(n) is not int or not 0<n<=min(model.support[a],model.support[b]):
                raise ValueError('Invalid directed edge')
            self.neighbors[a].append((b,n));incoming.add(b)
        self.incoming=frozenset(incoming)
        self.fallback=tuple(sorted(catalog.numeric,key=lambda i:(-self.p0.get(i,0),int(i))))

    def rank(self, query_ms, history):
        if not history or len(history)!=len(set(history)):
            raise ValueError('History must be a nonempty distinct set')
        scores=defaultdict(Fraction);supported=outgoing=0
        for i in history:
            p.item(i)
            if i not in self.model.support: continue
            supported+=1
            outgoing+=bool(self.neighbors.get(i))
            for j,n in self.neighbors.get(i,()):
                if self.catalog.contains(j,query_ms): scores[j]+=Fraction(n,self.model.support[i])
        count=self.catalog.size(query_ms);wanted=min(10,count)
        positive=sorted(scores,key=lambda i:(-scores[i],-self.p0.get(i,0),int(i)))
        ids=positive[:wanted]
        if len(ids)<wanted:
            selected=set(ids)
            for j in self.fallback:
                if j not in selected and self.catalog.contains(j,query_ms):
                    ids.append(j)
                    if len(ids)==wanted:break
        values=[scores.get(i,Fraction(0)) for i in ids]
        reason=None if positive else 'no_shared_supported_seed' if not supported else 'no_outgoing_seed' if not outgoing else 'no_positive_causal_neighbor'
        return {'fit_id':self.model.fit_id,'ids':ids,'scores':[[s.numerator,s.denominator] for s in values],
                'p0_counts':[self.p0.get(i,0) for i in ids],'candidate_count':count,
                'supported_seeds':supported,'outgoing_seeds':outgoing,'positive_candidates':len(positive),
                'zero_fill_slots':sum(s==0 for s in values),'fallback_reason':reason}


def bootstrap(records, reference_replicates, emit=None, watch=lambda: None):
    """New D1-C1 values; every draw identity must match the accepted C1 draw."""
    if np.__version__!='2.5.4':raise ValueError('Frozen NumPy version mismatch')
    grouped=defaultdict(list);ordered=[]
    for v,d in records:
        p.item(v)
        if type(d) is not float or not math.isfinite(d):raise ValueError('Nonfinite paired delta')
        grouped[v].append(d);ordered.append(d)
    reference=iter(reference_replicates)
    if not grouped:
        if next(reference,None) is not None:raise ValueError('Unexpected reference draws for no queries')
        return {'replicates':0,'visitors':0,'mean_delta':None,'interval':None,'reason':'zero_queries'}
    visitors=sorted(grouped,key=int);counts=[len(grouped[v]) for v in visitors];sums=[math.fsum(grouped[v]) for v in visitors]
    rng=np.random.Generator(np.random.PCG64(42));values=[]
    for b in range(2000):
        watch();before=rng.bit_generator.state
        draw=rng.integers(0,len(visitors),size=len(visitors),dtype=np.int64)
        weights=np.bincount(draw,minlength=len(visitors)).tolist()
        denominator=sum(w*n for w,n in zip(weights,counts))
        delta=math.fsum(w*d for w,d in zip(weights,sums))/denominator
        record={'replicate':b,'draw_sha256':hashlib.sha256(draw.astype('<i8',copy=False).tobytes(order='C')).hexdigest(),
                'query_denominator':denominator,'delta':delta,'rng_before':before,'rng_after':rng.bit_generator.state}
        old=next(reference,None)
        if old is None or any(type(old.get(k)) is not type(record[k]) or old[k]!=record[k]
                              for k in ('replicate','draw_sha256','query_denominator','rng_before','rng_after')):
            raise ValueError('C1 reference draw/RNG/query denominator mismatch')
        values.append(delta)
        if emit:emit(record)
    if next(reference,None) is not None:raise ValueError('Extra C1 reference bootstrap rows')
    return {'replicates':2000,'visitors':len(visitors),'mean_delta':math.fsum(ordered)/len(ordered),
            'interval':np.quantile(np.asarray(values,dtype=np.float64),[.025,.975],method='linear').tolist(),'reason':None}
