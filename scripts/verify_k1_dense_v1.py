"""Independent full enumeration of frozen August K1 predictions.

The session-by-item membership matrix is multiplied by a dense indicator for every
query. Each row includes every distinct train item, even for zero-overlap sessions.
The transpose gives every catalogue item a score. Small scaled votes are summed by
exact unsigned matrix multiplication. Larger votes use a full membership scan and
Python integer addition of every nonzero contribution. Both paths retain all zeros.
"""

import argparse
from array import array
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from copy import copy
import csv
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import heapq
import json
from math import gcd, lcm
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time

import numpy as np
import scipy
from scipy.sparse import csr_matrix


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT = 'reports/stage12/retailrocket_session_knn_v1_validation_attempt.json'
RUNTIME = 'shop-mysql-runtime'
ROWS, EDGES, ITEMS = 1_180_256, 1_587_436, 222_754
WORKERS = 2


def digest_json(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def same_json(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def number(text):
    if type(text) is not str or not text.isascii() or not text.isdecimal() or text != str(int(text)):
        raise ValueError('Invalid string item or visitor ID')
    return int(text)


class DenseModel:
    def __init__(self, sessions, counts, catalog, fit_id):
        self.fit_id = fit_id
        # Column order breaks score ties by P0 count then numeric item, including cold items.
        self.products = sorted(catalog, key=lambda i: (-counts.get(i, 0), i))
        self.columns = {i: c for c, i in enumerate(self.products)}
        self.times = np.array([catalog[i] for i in self.products], dtype=np.int64)
        self.counts = counts
        people, starts = array('q'), array('q')
        offsets, edges = array('i', [0]), array('i')
        previous = None
        max_size = 0
        for visitor, start, members in sessions:
            key = (visitor, start)
            if previous is not None and key <= previous:
                raise ValueError('Training session keys must be in ascending numeric order')
            if not members or any(a >= b for a, b in zip(members, members[1:])):
                raise ValueError('Expected distinct numerically ordered train items')
            previous = key
            people.append(visitor)
            starts.append(start)
            edges.extend(self.columns[i] for i in members)
            offsets.append(len(edges))
            max_size = max(max_size, len(members))
        self.people = np.frombuffer(people, dtype=np.int64)
        self.starts = np.frombuffer(starts, dtype=np.int64)
        size = (len(people), len(self.products))
        dtype = np.uint16 if max_size <= np.iinfo(np.uint16).max else np.uint32
        self.matrix = csr_matrix((np.ones(len(edges), dtype=dtype), np.frombuffer(edges, dtype=np.int32),
                                  np.frombuffer(offsets, dtype=np.int32)), shape=size)
        self.transpose = self.matrix.T.tocsr().astype(np.uint32)
        self.support = np.diff(self.transpose.indptr)
        self.lengths = np.diff(self.matrix.indptr)
        self.seeds = np.zeros(size[1], dtype=dtype)
        self.weights = np.zeros(size[0], dtype=np.uint32)
        self.voting_modes = Counter()
        self.candidates = 0

    def local_copy(self):
        other = copy(self)
        other.seeds, other.weights = np.zeros_like(self.seeds), np.zeros_like(self.weights)
        other.voting_modes = Counter()
        other.candidates = 0
        return other

    def current_row(self, visitor, start):
        lo, hi = self.people.searchsorted(visitor), self.people.searchsorted(visitor, side='right')
        if lo == hi:
            return None
        pos = lo + self.starts[lo:hi].searchsorted(start)
        return int(pos) if pos < hi and self.starts[pos] == start else None

    def pool(self, overlaps, history_size):
        sha = hashlib.sha256()
        groups = defaultdict(list)
        ratios = {}
        for sid in np.flatnonzero(overlaps).tolist():
            n = int(overlaps[sid])
            d = int(self.lengths[sid]) + history_size - n
            # Rows are visited in numeric session key order, including all tied rows.
            sha.update(b'[["%d",%d],%d,%d]\n' % (self.people[sid], self.starts[sid], n, d))
            if (n, d) not in ratios:
                g = gcd(n, d)
                ratios[n, d] = (n // g, d // g)
            groups[ratios[n, d]].append((sid, n, d))
        selected = []
        boundary = None
        ties = removed = 0
        for ratio in sorted(groups, key=lambda pair: Fraction(*pair), reverse=True):
            members = groups[ratio]
            needed = 500 - len(selected)
            selected.extend((sid, n, d, ratio) for sid, n, d in members[:needed])
            if len(selected) == 500:
                boundary, ties, removed = list(ratio), len(members), max(0, len(members) - needed)
                break
        return selected, sha.hexdigest(), sum(map(len, groups.values())), boundary, ties, removed

    def scores(self, selected, causal):
        unit = lcm(*(ratio[1] for _, _, _, ratio in selected))
        weights = {sid: n * (unit // d) for sid, _, _, (n, d) in selected}
        if sum(weights.values()) <= np.iinfo(np.uint32).max:
            ids = list(weights)
            self.weights[ids] = list(weights.values())
            scores = self.transpose @ self.weights  # full catalogue, including empty cold rows
            self.weights[ids] = 0
            positives = np.flatnonzero(causal & (scores != 0)).tolist()
            self.last_vote_mode = 'dense_uint32'
            self.voting_modes[self.last_vote_mode] += 1
            return unit, {i: int(scores[i]) for i in positives}

        # Multiply every membership by a dense 0/1 mask. This independently locates
        # all positive columns and counts their contributing edges without large-integer overflow.
        # Sum every nonzero term exactly from the selected sessions' original memberships.
        ids = list(weights)
        self.weights[ids] = 1
        incidence = self.transpose @ self.weights
        self.weights[ids] = 0
        scores = defaultdict(int)
        memberships = 0
        for sid, weight in weights.items():
            begin, end = self.matrix.indptr[sid:sid+2]
            memberships += int(end - begin)
            for col in self.matrix.indices[begin:end].tolist():
                scores[col] += weight
        if int(incidence.sum(dtype=np.uint64)) != memberships or np.count_nonzero(incidence) != len(scores):
            raise ValueError('Independent vote incidence mismatch')
        self.last_vote_mode = 'full_membership_scan_python_int'
        self.voting_modes[self.last_vote_mode] += 1
        return unit, {i: scores[i] for i in np.flatnonzero(causal & (incidence > 0)).tolist()}

    def predict(self, t, history, current):
        items = [number(i) for i in history]
        if (not items or len(items) != len(set(items)) or type(t) is not int or
                type(current[1]) is not int or not 0 <= current[1] <= t):
            raise ValueError('Invalid history or current session')
        cols = [self.columns[i] for i in items if i in self.columns]
        supported = sum(self.support[c] > 0 for c in cols)
        self.seeds[cols] = 1
        overlaps = self.matrix @ self.seeds  # explicitly compute one intersection per training session
        self.seeds[cols] = 0
        visits = int(overlaps.sum(dtype=np.uint64))
        self_row = self.current_row(number(current[0]), current[1])
        excluded = int(self_row is not None and overlaps[self_row] > 0)
        if self_row is not None:
            overlaps[self_row] = 0
        selected, pool_sha, total, boundary, ties, removed = self.pool(overlaps, len(items))
        causal = self.times < t
        eligible = int(np.count_nonzero(causal))
        self.candidates += eligible
        unit, scores = self.scores(selected, causal)
        ranking = heapq.nsmallest(10, scores, key=lambda col: (-scores[col], col))
        if len(ranking) < min(eligible, 10):
            zero = causal.copy()
            zero[list(scores)] = False
            ranking.extend(np.flatnonzero(zero)[:10-len(ranking)].tolist())
        result_scores = [Fraction(scores.get(i, 0), unit) for i in ranking]
        reason = None
        if not scores:
            if not supported:
                reason = 'no_supported_seed'
            elif not total:
                reason = 'only_self_session_overlap' if excluded else 'no_eligible_positive_neighbor'
            else:
                reason = 'no_positive_causal_vote'
        return {'fit_id': self.fit_id, 'ids': [str(self.products[i]) for i in ranking],
                'scores': [[s.numerator, s.denominator] for s in result_scores],
                'p0_counts': [self.counts.get(self.products[i], 0) for i in ranking],
                'candidate_count': eligible, 'history_size': len(items), 'supported_seeds': int(supported),
                'unknown_seeds': int(len(items) - supported), 'raw_posting_visits': visits,
                'current_session_excluded': excluded, 'eligible_neighbors': total, 'neighbor_pool_sha256': pool_sha,
                'selected_neighbors': [{'key': [str(self.people[s]), int(self.starts[s])], 'intersection': n,
                                        'union': d, 'similarity': list(r)} for s, n, d, r in selected],
                'selected_neighbor_count': len(selected), 'boundary_similarity': boundary,
                'boundary_ties_total': ties, 'boundary_ties_excluded': removed,
                'vote_memberships': sum(int(self.lengths[s]) for s, *_ in selected),
                'positive_candidates': len(scores), 'zero_fill_slots': sum(i not in scores for i in ranking),
                'fallback_reason': reason}


class ParallelReadback:
    """Independent per-thread vectors; retire bounded computations in original archive order."""

    def __init__(self, model, lo, hi):
        self.model, self.lo, self.hi = model, lo, hi
        self.local = threading.local()

    def verify_line(self, line):
        if not hasattr(self.local, 'model'):
            self.local.model = self.model.local_copy()
        model = self.local.model
        row = json.loads(line)
        key = row['key']
        if len(key) != 3 or not self.lo <= key[2] < self.hi:
            raise ValueError('Invalid development query')
        expected = model.predict(key[2], row['history'], key[:2])
        return (line, key, same_json(row['predictions']['K1'], expected),
                model.last_vote_mode, expected['candidate_count'])

    def lines(self, stream):
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            pending = deque()
            for line in stream:
                pending.append(executor.submit(self.verify_line, line))
                if len(pending) >= 2 * WORKERS:
                    yield pending.popleft().result()
            while pending:
                yield pending.popleft().result()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime():
    return {'python': sys.version.split()[0], 'implementation': platform.python_implementation(),
            'platform': sys.platform, 'numpy': np.__version__, 'scipy': scipy.__version__,
            'verifier_sha256': sha(Path(__file__))}


def write_json(path, result, *, replace=False):
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write('\n')
        if replace:
            os.replace(name, path)
        else:
            os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def bound(path, records, root):
    record = records[path.relative_to(root).as_posix()]
    if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
        raise ValueError('Frozen source differs: ' + path.name)
    return record


def csv_table(path, columns, cutoff=None):
    values = {}
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != columns:
            raise ValueError('Source schema mismatch')
        for row in reader:
            value = number(row[columns[1]])
            if cutoff is not None and value >= cutoff:
                continue
            key = number(row[columns[0]])
            if key in values:
                raise ValueError('Duplicate source item')
            values[key] = value
    return values


def run(out, deadline, root=ROOT):
    if deadline.tzinfo is None:
        raise ValueError('Expected a timezone-aware deadline')
    start = datetime.now(timezone.utc)
    clock = time.monotonic()
    stop = clock + (deadline - start).total_seconds()

    def watch():
        if time.monotonic() >= stop or datetime.now(timezone.utc) >= deadline:
            raise TimeoutError('Dense verification time budget elapsed')

    watch()
    out = Path(out).resolve()
    inputs = root / RUNTIME
    primary = inputs / 'retailrocket_session_knn_paired_v1'
    p0 = inputs / 'retailrocket_popularity_v1' / 'development'
    dataset = inputs / 'retailrocket_dataset_v1'
    if any(out.is_relative_to(path) for path in (primary, p0, dataset)):
        raise ValueError('The output folder must be separate from source archives')
    out.mkdir(exist_ok=True, parents=True)
    write_json(out / 'k1_dense.started.json', dict(started_utc=start.isoformat(), **runtime()))
    digest, roster = hashlib.sha256(), hashlib.sha256()
    progress = {'status': 'started', 'queries': 0}

    def checkpoint():
        state = dict(progress, elapsed_seconds=round(time.monotonic()-clock, 3),
                     prefix_query_sha256=digest.hexdigest(), prefix_roster_sha256=roster.hexdigest())
        write_json(out / 'k1_dense.progress.json', state, replace=True)

    try:
        doc = json.loads((root / ATTEMPT).read_bytes())
        spec_info = doc['specification']
        spec_path = root / spec_info['path']
        bound(spec_path, {spec_info['path']: spec_info}, root)
        spec = json.loads(spec_path.read_bytes())
        cfg = spec['configuration']
        records = {r['path']: r for r in [*doc['preservation']['execution_artifacts'], *spec['direct_input_bindings']]}
        sessions = primary / 'sessions.jsonl'
        query_path = primary / 'queries.jsonl'
        targets = (sessions, primary / 'fit_audit.json', p0 / 'item_counts.csv', dataset / 'catalog.csv')
        descriptors = [bound(p, records, root) for p in targets]
        qsource = records[query_path.relative_to(root).as_posix()]
        if query_path.stat().st_size != qsource['bytes']:
            raise ValueError('Archived query byte count mismatch')
        fit = json.loads(targets[1].read_bytes())
        counts = csv_table(targets[2], ['itemid', 'count'])
        lo, hi = cfg['validation_window_ms']
        catalog = csv_table(targets[3], ['itemid', 'first_view_ms'], cutoff=hi)
        fit_hash = hashlib.sha256(('K1_Jaccard_exact_session_k500_v1\n%d,%d\n' % tuple(cfg['train_window_ms'])).encode())

        def session_rows():
            with sessions.open('rb') as stream:
                for index, line in enumerate(stream):
                    if index % 8192 == 0:
                        watch()
                    raw = json.loads(line)
                    key, members = raw['key'], raw['items']
                    fit_hash.update(digest_json([key, members]) + b'\n')
                    yield number(key[0]), key[1], tuple(number(i) for i in members)

        model = DenseModel(session_rows(), counts, catalog, fit['fit_id'])
        n, m = model.matrix.shape
        e = model.matrix.nnz
        if (fit_hash.hexdigest() != model.fit_id or n != fit['train_sessions'] or
                e != fit['distinct_session_item_memberships'] or max(model.lengths, default=0) != fit['maximum_session_items']):
            raise ValueError('Dense training membership, shape or fit hash differs')
        progress.update(status='scanning', train_sessions=n, train_memberships=e, catalog_size=m)
        checkpoint()
        previous = None
        voting_modes = Counter()
        candidate_total = 0
        for_s = time.monotonic()
        next_report = for_s + 30
        with query_path.open('rb') as stream:
            for line, key, matches, voting, candidate in ParallelReadback(model, lo, hi).lines(stream):
                watch()
                if previous is not None and previous >= key:
                    raise ValueError('Unordered development query')
                if not matches:
                    raise ValueError('Dense predictions differ at query ' + str(progress['queries'] + 1))
                digest.update(line)
                roster.update(digest_json(key) + b'\n')
                previous = key
                voting_modes[voting] += 1
                candidate_total += candidate
                progress['queries'] += 1
                if progress['queries'] % 512 == 0 or time.monotonic() >= next_report:
                    progress.update(causal_candidate_scores_checked=candidate_total,
                                    completed_voting_modes=dict(voting_modes))
                    checkpoint()
                    print('Dense queries verified:', progress['queries'], flush=True)
                    next_report = time.monotonic() + 30
        q = progress['queries']
        if q != cfg['fixed_validation']['queries'] or digest.hexdigest() != qsource['sha256']:
            raise ValueError('Complete query count or SHA-256 differs')
        for path in targets:
            watch()
            bound(path, records, root)
        watch()
        result = dict(status='passed', queries=q, queries_sha256=digest.hexdigest(), roster_sha256=roster.hexdigest(),
                      fit_id=model.fit_id, train_sessions=n, train_memberships=int(e), catalog_size=m,
                      session_query_comparisons=n*q, membership_intersections_checked=int(e)*q,
                      vote_memberships_scanned=int(e)*q, catalog_query_comparisons=m*q,
                      causal_candidate_scores_checked=candidate_total, voting_modes=dict(voting_modes),
                      independent_query_threads=WORKERS,
                      intersection_dtype=str(model.matrix.dtype), maximum_session_items=int(max(model.lengths, default=0)),
                      vote_dtype='uint32 when all selected weights sum to <= 4294967295, otherwise Python int',
                      exact_jaccard_order='Fraction groups with stable numeric session order',
                      zero_fill='every causal catalogue item classified; P0 count then numeric ID',
                      query_eof_verified=True, test_ranked_queries=0, inputs=[spec_info, *descriptors, qsource],
                      started_utc=start.isoformat(), elapsed_seconds=time.monotonic()-clock,
                      prediction_seconds=time.monotonic()-for_s, **runtime())
        progress['status'] = 'passed'
        checkpoint()
        write_json(out / 'k1_dense.json', result)
        return result
    except Exception as exc:
        progress.update(status='incomplete', reason=type(exc).__name__ + ': ' + str(exc))
        checkpoint()
        raise


def benchmark():
    """Full-sized artificial memberships and histories, including a concentrated synthetic hot item."""
    stats_path = ROOT / 'reports/stage12/retailrocket_session_knn_v1_implementation_acceptance.json'
    stats = json.loads(stats_path.read_bytes())['train_only_cost']
    support = stats['positive_support_items']
    histogram = sorted((int(k), v) for k, v in stats['session_size_histogram'].items())

    def artificial_sessions():
        sid = 0
        for k, n in histogram:
            for group_index in range(n):
                first = (sid * 83) % (support - 2)
                members = [(first + j * 71) % (support - 2) for j in range(k)]
                if group_index == 0 and k > 1:
                    members[0] = support - 2  # widely differing similarity denominators
                elif sid % 700 == 0:
                    members[0] = support - 1
                yield sid, 0, tuple(sorted(members))
                sid += 1

    counts = {i: i % 7 + 1 for i in range(support)}
    catalog = {i: i % 25 for i in range(ITEMS)}
    model = DenseModel(artificial_sessions(), counts, catalog, 'a' * 64)
    if model.matrix.shape != (ROWS, ITEMS) or model.matrix.nnz != EDGES:
        raise ValueError('Full-sized artificial fixture mismatch')
    cases = []
    for j in range(32):
        for case in ('cold', 'short', 'mixed', 'hot', 'wide_integer'):
            items = [ITEMS + j] if case == 'cold' else [((j + 1) * 4729 + k * 71) % (support - 1)
                                                        for k in range(1 if case == 'short' else 8)]
            if case == 'hot':
                items.append(support - 1)
            if case == 'wide_integer':
                items = [support - 2, ITEMS + j]
            history = list(map(str, sorted(items)))
            key = [str(ROWS + j), 1, 26]
            prediction = model.predict(key[2], history, key[:2])
            cases.append((case, digest_json(dict(key=key, history=history, predictions={'K1': prediction}))))
    elapsed, modes = {}, Counter()
    digest = hashlib.sha256()
    for case in dict.fromkeys(name for name, _ in cases):
        start = time.perf_counter()
        lines = [line for name, line in cases if name == case]
        for line, key, matches, voting, _ in ParallelReadback(model, 0, 100).lines(lines):
            if not matches:
                raise ValueError('Artificial case changed')
            modes[voting] += 1
            digest.update(line)
        elapsed[case] = time.perf_counter() - start
    means = {k: v / 32 * 1000 for k, v in elapsed.items()}
    if set(modes) != {'dense_uint32', 'full_membership_scan_python_int'}:
        raise ValueError('Full-size benchmark must exercise both exact voting paths')
    print(json.dumps(dict(artificial=True, train_sessions=ROWS, membership_edges=EDGES, catalogue_items=ITEMS,
                          queries=len(cases), mean_ms_by_case=means, voting_modes=modes, query_threads=WORKERS,
                          all_case_mean_ms=sum(elapsed.values()) * 1000 / len(cases), **runtime())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--deadline-utc', type=datetime.fromisoformat)
    args = parser.parse_args()
    if args.benchmark:
        benchmark()
    elif args.out is None or args.deadline_utc is None:
        parser.error('--out and --deadline-utc are required for verification')
    else:
        run(args.out, args.deadline_utc)
