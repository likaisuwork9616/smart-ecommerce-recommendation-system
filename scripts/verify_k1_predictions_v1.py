"""Independently verify archived K1 train artifacts and August predictions.

Neighbor similarity and votes use only integers. For denominators at most M,
two unequal fractions differ by at least 1/M**2. Flooring M**2 times the fraction
therefore gives a tie-preserving, strictly increasing integer ordering. Votes
share the LCM of selected denominators and are reduced only for displayed scores.
"""
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from contextlib import ExitStack
import csv
from datetime import datetime, timezone
import hashlib
from itertools import groupby, islice
import json
from math import gcd, lcm
from pathlib import Path
import time


TRAIN = (1430697600000, 1438387200000)
VALIDATION = (1438387200000, 1441065600000)
EXPECTED_QUERIES = 166897
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'shop-mysql-runtime'
PRIMARY = DATA / 'retailrocket_session_knn_paired_v1'
C1 = DATA / 'retailrocket_cooccurrence_paired_v1'
P0 = DATA / 'retailrocket_popularity_v1' / 'development'
SOURCE = DATA / 'retailrocket_dataset_v1'
BASKET_HEADER = ['visitorid', 'session_start_ms', 'query_ms', 'role', 'basket_index',
                 'items', 'source_records', 'context_item_occurrences']


def numeric(value):
    if type(value) is not str or not value.isascii() or not value.isdecimal() or str(int(value)) != value:
        raise ValueError('Noncanonical numeric ID or source integer')
    return int(value)


def exact(observed, expected):
    # The serialization also distinguishes integer, boolean, and float scalars.
    opts = dict(sort_keys=True, separators=(',', ':'), allow_nan=False)
    return json.dumps(observed, **opts) == json.dumps(expected, **opts)


def compact(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('ascii')


def fraction_pair(numerator, denominator):
    divisor = gcd(numerator, denominator)
    return [numerator // divisor, denominator // divisor]


class Model:
    def __init__(self, sessions, counts, catalog, fit_id):
        self.sessions = sessions
        self.counts = counts
        self.catalog = catalog
        self.fit_id = fit_id
        self.keys = []
        self.key_json = []
        self.pool_prefix = []
        self.postings = defaultdict(list)
        self.max_size = 0
        for sid, (v, start, members) in enumerate(sessions):
            if (not members or (self.keys and self.keys[-1] >= (v, start)) or
                    tuple(sorted(set(members))) != members):
                raise ValueError('Train membership/order')
            self.keys.append((v, start))
            self.key_json.append([str(v), start])
            self.pool_prefix.append(b'[' + compact(self.key_json[-1]) + b',')
            self.max_size = max(self.max_size, len(members))
            for item in members:
                self.postings[item].append(sid)
        self.first_times = sorted(catalog.values())
        self.fallback = sorted(catalog, key=lambda i: (-counts.get(i, 0), i))

    def predict(self, t, history, current):
        seeds = [numeric(i) for i in history]
        key = (numeric(current[0]), current[1])
        if not seeds or len(seeds) != len(set(seeds)) or type(key[1]) is not int or type(t) is not int or key[1] > t:
            raise ValueError('Invalid query history or clock')
        # A row absent from the union of all seed postings has zero overlap.
        overlaps = Counter()
        supported = 0
        for seed in seeds:
            posting = self.postings.get(seed)
            if posting:
                supported += 1
                overlaps.update(posting)
        visits = sum(overlaps.values())
        self_row = bisect_left(self.keys, key)
        excluded = 0
        if self_row < len(self.keys) and self.keys[self_row] == key:
            excluded = int(overlaps.pop(self_row, 0) > 0)

        pool_hash = hashlib.sha256()
        scale = (len(seeds) + self.max_size) ** 2
        pool = []
        for row in sorted(overlaps):
            intersection = overlaps[row]
            union = len(seeds) + len(self.sessions[row][2]) - intersection
            pool_hash.update(self.pool_prefix[row] + b'%d,%d]\n' % (intersection, union))
            pool.append((-(intersection * scale // union), row, intersection, union))
        pool.sort()
        selected = pool[:500]
        ties = removed = 0
        boundary = None
        if len(selected) == 500:
            code, _, n, d = selected[-1]
            boundary = fraction_pair(n, d)
            ties = sum(entry[0] == code for entry in pool)
            removed = ties - sum(entry[0] == code for entry in selected)

        unit = lcm(*(set(entry[3] for entry in selected)))
        votes = defaultdict(int)
        evidence = []
        memberships = 0
        for _, row, intersection, union in selected:
            contribution = intersection * (unit // union)
            members = self.sessions[row][2]
            memberships += len(members)
            evidence.append({'key': self.key_json[row], 'intersection': intersection, 'union': union,
                             'similarity': fraction_pair(intersection, union)})
            for item in members:
                if self.catalog[item] < t:
                    votes[item] += contribution
        eligible = bisect_left(self.first_times, t)
        wanted = min(eligible, 10)
        ranked = sorted(votes, key=lambda i: (-votes[i], -self.counts.get(i, 0), i))[:wanted]
        if len(ranked) < wanted:
            for item in self.fallback:
                if item not in votes and self.catalog[item] < t:
                    ranked.append(item)
                    if len(ranked) == wanted:
                        break
        reason = None
        if not votes:
            if not supported:
                reason = 'no_supported_seed'
            elif excluded and not pool:
                reason = 'only_self_session_overlap'
            elif not pool:
                reason = 'no_eligible_positive_neighbor'
            else:
                reason = 'no_positive_causal_vote'
        return {
            'fit_id': self.fit_id, 'ids': [str(i) for i in ranked],
            'scores': [fraction_pair(votes.get(i, 0), unit) for i in ranked],
            'p0_counts': [self.counts.get(i, 0) for i in ranked],
            'candidate_count': eligible, 'history_size': len(seeds), 'supported_seeds': supported,
            'unknown_seeds': len(seeds) - supported, 'raw_posting_visits': visits,
            'current_session_excluded': excluded, 'eligible_neighbors': len(pool),
            'neighbor_pool_sha256': pool_hash.hexdigest(), 'selected_neighbors': evidence,
            'selected_neighbor_count': len(selected), 'boundary_similarity': boundary,
            'boundary_ties_total': ties, 'boundary_ties_excluded': removed,
            'vote_memberships': memberships, 'positive_candidates': len(votes),
            'zero_fill_slots': sum(i not in votes for i in ranked), 'fallback_reason': reason,
        }


def rows(stream, header):
    reader = csv.DictReader(stream)
    if reader.fieldnames != header:
        raise ValueError('Source table schema mismatch')
    for record in reader:
        if None in record or None in record.values():
            raise ValueError('Source table width mismatch')
        yield record


def train_baskets(stream):
    last = None
    for r in rows(stream, BASKET_HEADER):
        if r['role'] != 'train':
            continue
        # Skip every other role before decoding its identity, timestamps or payload.
        v = r['visitorid']
        numeric(v)
        start, t = numeric(r['session_start_ms']), numeric(r['query_ms'])
        key = (v, start, t)
        if not TRAIN[0] <= t < TRAIN[1] or start > t or (last and key <= last):
            raise ValueError('Training clock or source order mismatch')
        last = key
        payload = json.loads(r['items'])
        if type(payload) is not list or not payload or len(payload) != len(set(payload)):
            raise ValueError('Duplicate or empty train basket')
        yield (v, start), tuple(numeric(i) for i in payload)


def require_next(stream, expected, label):
    raw = next(stream, None)
    if raw is None or not exact(json.loads(raw), expected):
        raise ValueError('Training evidence mismatch: ' + label)


def require_eof(stream, label):
    if next(stream, None) is not None:
        raise ValueError('Additional rows in ' + label)


def load_table(path, header):
    result = {}
    with path.open(encoding='utf-8', newline='') as stream:
        for row in rows(stream, header):
            item, count = numeric(row[header[0]]), numeric(row[header[1]])
            if item in result or not count:
                raise ValueError('Duplicate item or nonpositive count')
            result[item] = count
    return result


def load_catalog():
    catalog = {}
    with (SOURCE / 'catalog.csv').open(encoding='utf-8', newline='') as stream:
        for row in rows(stream, ['itemid', 'first_view_ms']):
            first = numeric(row['first_view_ms'])
            if first >= VALIDATION[1]:
                continue
            item = numeric(row['itemid'])
            if item in catalog:
                raise ValueError('Duplicate pre-cutoff catalogue item')
            catalog[item] = first
    return catalog


def build(watch):
    sessions = []
    baskets = occurrences = 0
    with ExitStack() as opened:
        source = opened.enter_context((SOURCE / 'baskets.csv').open(encoding='utf-8', newline=''))
        lineage = [opened.enter_context((p / 'train_sessions.jsonl').open('rb')) for p in (PRIMARY, C1)]
        for key, group in groupby(train_baskets(source), key=lambda entry: entry[0]):
            if len(sessions) % 4096 == 0:
                watch()
            members = set()
            n = m = 0
            for _, items in group:
                members.update(items)
                n += 1
                m += len(items)
            ordered = tuple(sorted(members))
            v, start = key
            expected = {'key': [v, start], 'items': [str(i) for i in ordered],
                        'baskets': n, 'basket_memberships': m}
            for stream in lineage:
                require_next(stream, expected, 'train session lineage')
            sessions.append((int(v), start, ordered))
            baskets += n
            occurrences += m
        for stream in lineage:
            require_eof(stream, 'train session lineage')
    sessions.sort()
    fit = hashlib.sha256(f'K1_Jaccard_exact_session_k500_v1\n{TRAIN[0]},{TRAIN[1]}\n'.encode())
    with (PRIMARY / 'sessions.jsonl').open('rb') as stream:
        for sid, (v, start, members) in enumerate(sessions):
            if sid % 4096 == 0:
                watch()
            key, items = [str(v), start], [str(i) for i in members]
            require_next(stream, {'key': key, 'items': items}, 'numeric-order sessions')
            fit.update(compact([key, items]) + b'\n')
        require_eof(stream, 'numeric-order sessions')

    counts = load_table(P0 / 'item_counts.csv', ['itemid', 'count'])
    support = load_table(C1 / 'support.csv', ['itemid', 'support'])
    model = Model(sessions, counts, load_catalog(), fit.hexdigest())
    if set(counts) != model.postings.keys() or set(support) != model.postings.keys():
        raise ValueError('P0/C1 training support keys mismatch')
    with (PRIMARY / 'postings.jsonl').open('rb') as stream:
        for item in sorted(model.postings):
            watch()
            posting = model.postings[item]
            if (support[item] != len(posting) or counts[item] < support[item]
                    or model.catalog[item] >= TRAIN[1]):
                raise ValueError('Training support/availability mismatch')
            require_next(stream, {'itemid': str(item), 'sessions': [model.key_json[sid] for sid in posting],
                                  'support': len(posting)}, 'complete postings')
        require_eof(stream, 'complete postings')
    audit = {'start_ms': TRAIN[0], 'end_ms': TRAIN[1], 'train_sessions': len(sessions),
             'singleton_sessions': sum(len(r[2]) == 1 for r in sessions),
             'train_baskets': baskets, 'basket_item_memberships': occurrences,
             'distinct_session_item_memberships': sum(support.values()), 'positive_support_items': len(support),
             'maximum_session_items': model.max_size, 'maximum_posting_size': max(support.values()),
             'fit_id': model.fit_id}
    if not exact(json.loads((PRIMARY / 'fit_audit.json').read_bytes()), audit):
        raise ValueError('Frozen fit audit differs from original train baskets')
    return model, audit


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(out, limit, deadline):
    def watch():
        if datetime.now(timezone.utc) >= deadline:
            raise TimeoutError('K1 verification deadline reached')
    watch()
    out.mkdir(parents=True, exist_ok=True)
    receipt_file = out / 'k1_predictions.json'
    if receipt_file.exists():
        raise FileExistsError('K1 prediction receipt already exists')
    # A duplicate invocation or interrupted process cannot claim this stage again.
    with (out / 'k1_predictions.started.json').open('x', encoding='utf-8') as marker:
        json.dump({'started_utc': datetime.now(timezone.utc).isoformat(), 'engineering_limit': limit}, marker)
    started = datetime.now(timezone.utc)
    tic = time.monotonic()
    model, fit = build(watch)
    built = time.monotonic()
    print(f'Train artifacts verified in {built-tic:.3f}s', flush=True)
    digest = hashlib.sha256()
    roster = hashlib.sha256()
    previous = None
    checked = 0
    with (PRIMARY / 'queries.jsonl').open('rb') as stream:
        for row in islice(stream, limit):
            watch()
            digest.update(row)
            record = json.loads(row)
            key = record['key']
            if (type(key) is not list or len(key) != 3 or
                    not VALIDATION[0] <= key[2] < VALIDATION[1] or (previous and key <= previous)):
                raise ValueError(f'August key clock/order mismatch at query {checked+1}')
            previous = key
            roster.update(compact(key) + b'\n')
            expected = model.predict(key[2], record['history'], key[:2])
            if not exact(record['predictions']['K1'], expected):
                raise ValueError(f'K1 nested prediction mismatch at query {checked+1}')
            checked += 1
            if checked == 512 or checked % 10000 == 0:
                print(f'{checked} complete nested predictions checked in {time.monotonic()-built:.3f}s', flush=True)
    if checked != (EXPECTED_QUERIES if limit is None else limit):
        raise ValueError('Unexpected query count')
    validated = time.monotonic()
    paths = [SOURCE / 'baskets.csv', SOURCE / 'catalog.csv', C1 / 'support.csv', C1 / 'train_sessions.jsonl',
             P0 / 'item_counts.csv', *(PRIMARY / n for n in ('fit_audit.json', 'sessions.jsonl',
                                                              'postings.jsonl', 'train_sessions.jsonl'))]
    fingerprints = {}
    for path in paths:
        watch()
        fingerprints[path.relative_to(ROOT).as_posix()] = file_sha(path)
    watch()
    receipt = {'status': 'passed' if limit is None else 'engineering_prefix_only',
               'scope': 'archived August development predictions; training source role filtered before item decoding',
               'queries': checked, 'query_eof_verified': limit is None,
               'queries_sha256' if limit is None else 'prefix_bytes_sha256': digest.hexdigest(),
               'roster_sha256': roster.hexdigest(),
               'fit_audit': fit, 'source_sha256': fingerprints, 'verifier_sha256': file_sha(Path(__file__)),
               'started_utc': started.isoformat(), 'completed_utc': datetime.now(timezone.utc).isoformat(),
               'training_verification_seconds': built-tic, 'prediction_verification_seconds': validated-built}
    with receipt_file.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new directory for this run')
    parser.add_argument('--limit', type=int, help='engineering prefix; never issues a full receipt')
    parser.add_argument('--deadline-utc', required=True, type=datetime.fromisoformat)
    args = parser.parse_args()
    if args.limit is not None and not 0 < args.limit <= EXPECTED_QUERIES:
        parser.error('limit must be a positive development prefix')
    if args.deadline_utc.tzinfo is None:
        parser.error('deadline must include timezone')
    verify(args.out, args.limit, args.deadline_utc)


if __name__ == '__main__':
    main()
