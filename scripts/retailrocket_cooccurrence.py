"""Exact binary-session C1, causal prefix history and paired cluster bootstrap."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from types import MappingProxyType
import numpy as np

from scripts import retailrocket_popularity as p


@dataclass(frozen=True)
class Basket:
    visitor: str
    session: int
    time: int
    role: str
    index: int
    items: tuple
    def key(self):
        return self.visitor, self.session, self.time


def session_sets(baskets, start, end):
    key = previous = None
    members = set()
    n = occurrences = 0
    for b in baskets:
        if b.role != 'train':
            continue
        p.item(b.visitor)
        if not start <= b.time < end or b.session > b.time or b.index < 1:
            raise ValueError('Train role/time/index mismatch')
        if previous is not None and b.key() <= previous:
            raise ValueError('Duplicate/unordered fit basket')
        previous = b.key()
        current = b.key()[:2]
        if key is not None and current != key:
            yield key, members, n, occurrences
            members = set()
            n = occurrences = 0
        key = current
        if not b.items or len(b.items) != len(set(b.items)):
            raise ValueError('Empty/duplicate basket membership')
        for i in b.items:
            members.add(p.item(i))
        n += 1
        occurrences += len(b.items)
    if key is not None:
        yield key, members, n, occurrences


def identity(support, pairs, start, end):
    h = hashlib.sha256(f'C1_binary_session_conditional_sum_v1\n{start},{end}\n'.encode())
    for i in sorted(support, key=int):
        h.update(f'S,{i},{support[i]}\n'.encode())
    for a, b in sorted(pairs, key=lambda x: (int(x[0]), int(x[1]))):
        h.update(f'C,{a},{b},{pairs[a,b]}\n'.encode())
    return h.hexdigest()


@dataclass(frozen=True)
class Model:
    support: object
    pairs: object
    fit_id: str
    audit: object


def fit(baskets, start, end, p0_counts, emit_session=None, watch=lambda: None):
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError('Invalid training clock')
    support, pairs = Counter(), Counter()
    sessions = singleton = emissions = baskets_n = occurrences = 0
    for key, members, n, o in session_sets(baskets, start, end):
        watch()
        ids = sorted(members, key=int)
        sessions += 1
        singleton += len(ids) == 1
        baskets_n += n
        occurrences += o
        support.update(ids)
        for pos, a in enumerate(ids):
            for b in ids[pos + 1:]:
                pairs[a,b] += 1
                emissions += 1
                if emissions % 50000 == 0:
                    watch()
        if emit_session:
            emit_session(key, ids, n, o)
    if set(support) != set(p0_counts) or any(support[i] > p0_counts[i] for i in support):
        raise ValueError('C1 support/P0 key or upper-bound mismatch')
    if any(not 0 < n <= min(support[a], support[b]) or int(a) >= int(b) for (a,b), n in pairs.items()):
        raise ValueError('Pair support invariant failed')
    audit = {'train_sessions': sessions, 'singleton_sessions': singleton, 'train_baskets': baskets_n,
             'basket_item_memberships': occurrences, 'distinct_session_item_memberships': sum(support.values()),
             'exact_unordered_pair_emissions': emissions, 'unique_pairs': len(pairs),
             'positive_support_items': len(support), 'start_ms': start, 'end_ms': end}
    if sum(pairs.values()) != emissions:
        raise ValueError('Pair sum invariant')
    return Model(MappingProxyType(dict(support)), MappingProxyType(dict(pairs)),
                 identity(support, pairs, start, end), MappingProxyType(audit))


class Histories:
    """Streaming prefix join; current basket must exist at the exact index/time."""
    def __init__(self, baskets):
        self.source = iter(baskets)
        self.next = next(self.source, None)
        self.session = self.last = self.previous_query = None
        self.members = set()
        self.current = None
    def at(self, q, index):
        if q.role != 'validation' or (self.previous_query is not None and q.key() <= self.previous_query):
            raise ValueError('History query role/order')
        self.previous_query = q.key()
        while self.next is not None and self.next.key() <= q.key():
            b = self.next
            if b.role not in ('warmup', 'train', 'validation'):
                raise ValueError('Forbidden history role')
            if self.last is not None and b.key() <= self.last:
                raise ValueError('History source duplicate/order')
            if self.session != b.key()[:2]:
                self.session = b.key()[:2]
                self.members = set()
                expected_index = 1
            else:
                expected_index = self.current.index + 1
            if b.index != expected_index or not b.items or len(set(b.items)) != len(b.items):
                raise ValueError('History basket index/membership')
            self.members.update(p.item(i) for i in b.items)
            self.last = b.key()
            self.current = b
            self.next = next(self.source, None)
        if self.last != q.key() or self.current.index != index or (q.current_size and len(self.current.items) != q.current_size) or not self.members:
            raise ValueError('Missing exact current history basket')
        return tuple(sorted(self.members, key=int))


class Ranker:
    def __init__(self, model, p0_counts, catalog):
        self.model, self.p0, self.catalog = model, p0_counts, catalog
        if set(model.support) != set(p0_counts) or any(i not in catalog.first for i in model.support):
            raise ValueError('Ranker support/catalog mismatch')
        self.neighbors = defaultdict(list)
        for (a,b), n in model.pairs.items():
            self.neighbors[a].append((b,n))
            self.neighbors[b].append((a,n))
        self.fallback = tuple(sorted(catalog.numeric, key=lambda i: (-p0_counts.get(i,0), int(i))))
    def rank(self, query_ms, history):
        if not history or len(history) != len(set(history)):
            raise ValueError('History must be a nonempty distinct set')
        scores = defaultdict(Fraction)
        supported = 0
        for i in history:
            p.item(i)
            if i not in self.model.support:
                continue
            supported += 1
            for j, n in self.neighbors.get(i, ()):
                if self.catalog.contains(j, query_ms):
                    scores[j] += Fraction(n, self.model.support[i])
        count = self.catalog.size(query_ms)
        positive = sorted(scores, key=lambda i: (-scores[i], -self.p0.get(i,0), int(i)))
        ids = positive[:min(10,count)]
        if len(ids) < min(10,count):
            selected = set(ids)
            for j in self.fallback:
                if j not in selected and self.catalog.contains(j,query_ms):
                    ids.append(j)
                    if len(ids) == min(10,count):
                        break
        values = [scores.get(i,Fraction(0)) for i in ids]
        return {'fit_id': self.model.fit_id, 'ids': ids, 'scores': [[x.numerator,x.denominator] for x in values],
                'p0_counts': [self.p0.get(i,0) for i in ids], 'candidate_count': count,
                'supported_seeds': supported, 'positive_candidates': len(positive),
                'zero_fill_slots': sum(x == 0 for x in values),
                'fallback_reason': None if positive else 'no_supported_seeds' if not supported else 'no_positive_causal_neighbor'}


def bootstrap(records, emit=None, watch=lambda: None):
    if np.__version__ != '2.5.4':
        raise ValueError('Frozen NumPy version mismatch')
    grouped = defaultdict(list)
    ordered_deltas = []
    for visitor, delta in records:
        p.item(visitor)
        if type(delta) is not float or not math.isfinite(delta):
            raise ValueError('Nonfinite paired delta')
        grouped[visitor].append(delta)
        ordered_deltas.append(delta)
    if not grouped:
        return {'replicates': 0, 'visitors': 0, 'mean_delta': None, 'interval': None, 'reason': 'zero_queries'}
    visitors = sorted(grouped, key=int)
    counts = [len(grouped[v]) for v in visitors]
    sums = [math.fsum(grouped[v]) for v in visitors]
    rng = np.random.Generator(np.random.PCG64(42))
    values = []
    for b in range(2000):
        watch()
        before = rng.bit_generator.state
        draw = rng.integers(0,len(visitors),size=len(visitors),dtype=np.int64)
        weights = np.bincount(draw, minlength=len(visitors)).tolist()
        denominator = sum(w*n for w,n in zip(weights,counts))
        delta = math.fsum(w*d for w,d in zip(weights,sums)) / denominator
        values.append(delta)
        if emit:
            emit({'replicate': b, 'draw_sha256': hashlib.sha256(draw.astype('<i8',copy=False).tobytes(order='C')).hexdigest(),
                  'query_denominator': denominator, 'delta': delta,
                  'rng_before': before, 'rng_after': rng.bit_generator.state})
    return {'replicates': 2000, 'visitors': len(visitors), 'mean_delta': math.fsum(ordered_deltas)/len(ordered_deltas),
            'interval': np.quantile(np.asarray(values,dtype=np.float64),[.025,.975],method='linear').tolist(),
            'reason': None}
