"""K1 v1: exact complete-pool Jaccard session neighbors and causal voting."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import heapq
import json
from types import MappingProxyType

from scripts import retailrocket_popularity as p
from scripts.retailrocket_cooccurrence import Basket, Histories
from scripts.retailrocket_directed import bootstrap  # fixed, algorithm-neutral paired draws

NEIGHBORS = 500


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def session_order(key):
    return int(key[0]), key[1]


def train_sets(baskets, start, end, watch=lambda: None):
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('Invalid train window')
    current = previous = last_index = None
    members = set()
    n = occurrences = 0
    for b in baskets:
        watch()
        if b.role != 'train':
            continue
        p.item(b.visitor)
        if (any(type(v) is not int for v in (b.session,b.time,b.index))
                or not start <= b.time < end or not 0 <= b.session <= b.time or b.index < 1):
            raise ValueError('Train clock/index mismatch')
        if previous is not None and b.key() <= previous:
            raise ValueError('Duplicate/unordered train basket')
        previous = b.key()
        key = (b.visitor,b.session)
        if current is not None and key != current:
            yield {'key':list(current),'items':sorted(members,key=int),'baskets':n,'basket_memberships':occurrences}
            members = set(); n = occurrences = 0; last_index = None
        current = key
        if last_index is not None and b.index <= last_index:
            raise ValueError('Nonincreasing train basket index')
        last_index = b.index
        if not b.items or len(b.items) != len(set(b.items)):
            raise ValueError('Empty/duplicate basket membership')
        for i in b.items:
            members.add(p.item(i))
        n += 1; occurrences += len(b.items)
    if current is not None:
        yield {'key':list(current),'items':sorted(members,key=int),'baskets':n,'basket_memberships':occurrences}


def identity(sessions, start, end, watch=lambda:None):
    h = hashlib.sha256(f'K1_Jaccard_exact_session_k500_v1\n{start},{end}\n'.encode())
    for key in sorted(sessions,key=session_order):
        watch()
        h.update((encoded([list(key), sorted(sessions[key],key=int)])+'\n').encode())
    return h.hexdigest()


@dataclass(frozen=True)
class Model:
    sessions: object
    postings: object
    support: object
    fit_id: str
    audit: object


def fit(baskets, start, end, shared_support, p0_counts, emit_session=None, watch=lambda: None):
    support = dict(shared_support)
    if set(support) != set(p0_counts):
        raise ValueError('C1/P0 support keys differ')
    for i,n in support.items():
        p.item(i)
        if type(n) is not int or n <= 0 or type(p0_counts[i]) is not int or p0_counts[i] < n:
            raise ValueError('Invalid C1/P0 support')
    sessions = {}; postings = defaultdict(list)
    total_baskets = occurrences = singleton = 0
    for row in train_sets(baskets,start,end,watch):
        key = tuple(row['key']); items = frozenset(row['items'])
        if key in sessions:
            raise ValueError('Duplicate train session')
        sessions[key] = items
        for i in items:
            postings[i].append(key)
        singleton += len(items) == 1
        total_baskets += row['baskets']; occurrences += row['basket_memberships']
        if emit_session:
            emit_session(row)
    computed = {i:len(keys) for i,keys in postings.items()}
    if computed != support:
        raise ValueError('Complete postings differ from C1 support')
    frozen_postings = {i:tuple(sorted(keys,key=session_order)) for i,keys in postings.items()}
    audit = {'start_ms':start,'end_ms':end,'train_sessions':len(sessions),'singleton_sessions':singleton,
             'train_baskets':total_baskets,'basket_item_memberships':occurrences,
             'distinct_session_item_memberships':sum(support.values()),'positive_support_items':len(support),
             'maximum_session_items':max(map(len,sessions.values()),default=0),
             'maximum_posting_size':max(support.values(),default=0)}
    return Model(MappingProxyType(sessions),MappingProxyType(frozen_postings),MappingProxyType(support),
                 identity(sessions,start,end,watch),MappingProxyType(audit))


def model_payload(model):
    return {'fit_id':model.fit_id,'audit':dict(model.audit),
            'sessions':[{'key':list(key),'items':sorted(model.sessions[key],key=int)}
                        for key in sorted(model.sessions,key=session_order)],
            'postings':[{'itemid':i,'sessions':[list(k) for k in model.postings[i]],'support':model.support[i]}
                        for i in sorted(model.postings,key=int)]}


class Ranker:
    def __init__(self, model, p0_counts, catalog, watch=lambda:None):
        self.model,self.p0,self.catalog = model,dict(p0_counts),catalog
        if set(model.support) != set(self.p0):
            raise ValueError('Ranker support/P0 keys differ')
        # Inspect both directions. A damaged posting cannot quietly truncate neighbors.
        count = Counter()
        for key,members in model.sessions.items():
            watch()
            p.item(key[0]); p.integer(key[1])
            if not members:
                raise ValueError('Empty indexed session')
            for i in members:
                p.item(i); count[i] += 1
        if dict(count) != dict(model.support) or set(model.postings) != set(count):
            raise ValueError('Index membership/support mismatch')
        for i,keys in model.postings.items():
            watch()
            if (len(keys) != count[i] or len(set(keys)) != len(keys)
                    or tuple(sorted(keys,key=session_order)) != keys
                    or any(k not in model.sessions or i not in model.sessions[k] for k in keys)):
                raise ValueError('Incomplete/invalid posting')
            if (type(self.p0[i]) is not int or self.p0[i] < count[i]
                    or i not in catalog.first or catalog.first[i] >= model.audit['end_ms']):
                raise ValueError('Invalid P0 count or train catalog clock')
        if identity(model.sessions,model.audit['start_ms'],model.audit['end_ms'],watch) != model.fit_id:
            raise ValueError('Index fit identity mismatch')
        self.fallback = tuple(sorted(catalog.numeric,key=lambda i:(-self.p0.get(i,0),int(i))))

    def rank(self, query_ms, history, session_key, watch=lambda: None):
        p.integer(query_ms)
        if query_ms < self.model.audit['end_ms']:
            raise ValueError('Training scoring forbidden')
        if len(session_key) != 2:
            raise ValueError('Missing current session key')
        visitor,session = session_key
        p.item(visitor);p.integer(session)
        if session > query_ms or not history or len(history) != len(set(history)):
            raise ValueError('Invalid session/history')
        for i in history:
            p.item(i)
        key = (visitor,session); overlaps = Counter(); visits = 0
        for i in history:
            for neighbor in self.model.postings.get(i,()):
                overlaps[neighbor] += 1; visits += 1
                if visits % 4096 == 0:
                    watch()
        excluded = int(key in overlaps)
        overlaps.pop(key,None)
        def similarity(k):
            return Fraction(overlaps[k],len(history)+len(self.model.sessions[k])-overlaps[k])
        order = lambda k:(-similarity(k),int(k[0]),k[1])
        selected = heapq.nsmallest(NEIGHBORS,overlaps,key=order)
        pool = hashlib.sha256()
        for k in sorted(overlaps,key=session_order):
            watch()
            pool.update((encoded([list(k),overlaps[k],len(history)+len(self.model.sessions[k])-overlaps[k]])+'\n').encode())
        boundary = similarity(selected[-1]) if len(selected) == NEIGHBORS else None
        boundary_total = sum(similarity(k) == boundary for k in overlaps) if boundary is not None else 0
        boundary_selected = sum(similarity(k) == boundary for k in selected) if boundary is not None else 0
        scores = defaultdict(Fraction); neighbors = []; votes = 0
        for k in selected:
            watch(); sim = similarity(k)
            neighbors.append({'key':list(k),'intersection':overlaps[k],
                'union':len(history)+len(self.model.sessions[k])-overlaps[k],
                'similarity':[sim.numerator,sim.denominator]})
            for j in self.model.sessions[k]:
                votes += 1
                if self.catalog.contains(j,query_ms):
                    scores[j] += sim
                if votes % 4096 == 0:
                    watch()
        count = self.catalog.size(query_ms); wanted = min(10,count)
        positive = sorted(scores,key=lambda i:(-scores[i],-self.p0.get(i,0),int(i)))
        ids = positive[:wanted]
        if len(ids) < wanted:
            chosen = set(ids)
            for j in self.fallback:
                watch()
                if j not in chosen and self.catalog.contains(j,query_ms):
                    ids.append(j)
                    if len(ids) == wanted:
                        break
        supported = sum(i in self.model.support for i in history)
        reason = None
        if not positive:
            reason = ('no_supported_seed' if not supported else 'only_self_session_overlap' if excluded and not overlaps
                      else 'no_eligible_positive_neighbor' if not overlaps else 'no_positive_causal_vote')
        values = [scores.get(i,Fraction(0)) for i in ids]
        return {'fit_id':self.model.fit_id,'ids':ids,'scores':[[s.numerator,s.denominator] for s in values],
                'p0_counts':[self.p0.get(i,0) for i in ids],'candidate_count':count,
                'history_size':len(history),'supported_seeds':supported,'unknown_seeds':len(history)-supported,
                'raw_posting_visits':visits,'current_session_excluded':excluded,'eligible_neighbors':len(overlaps),
                'neighbor_pool_sha256':pool.hexdigest(),'selected_neighbors':neighbors,'selected_neighbor_count':len(selected),
                'boundary_similarity':None if boundary is None else [boundary.numerator,boundary.denominator],
                'boundary_ties_total':boundary_total,'boundary_ties_excluded':boundary_total-boundary_selected,
                'vote_memberships':votes,'positive_candidates':len(positive),
                'zero_fill_slots':sum(s == 0 for s in values),'fallback_reason':reason}
