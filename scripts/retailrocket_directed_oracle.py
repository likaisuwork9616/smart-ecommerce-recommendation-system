"""Independent SQL D1 reconstruction, three-arm readback and cluster replay.

No imports from the new D1 production core, adapter or bootstrap. The frozen
P0 Decimal/Fraction metric oracle is reused; all D1 counts and ranks are rebuilt.
"""
from bisect import bisect_left
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import groupby
import hashlib
import json
import math
import sqlite3
import struct
import numpy as np

from scripts.retailrocket_popularity_oracle import Fold, close, terms, read_rows, num, ms, GROUPS, METRICS, FIELDS


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def jsonlines(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def exact(actual, expected, where):
    # Canonical JSON distinguishes bool/int and 0.0/-0.0 in copied controls.
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise ValueError('Oracle exact reference differs: ' + where)


def digest_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_bootstrap(path, reference_path, records, watch=lambda: None):
    """Independent Counter draws, struct encoding and explicit quantile interpolation."""
    if np.__version__ != '2.5.4':
        raise ValueError('Oracle frozen NumPy version mismatch')
    grouped = defaultdict(list)
    for v, d in records:
        num(v)
        if type(d) is not float or not math.isfinite(d):
            raise ValueError('Oracle invalid paired bootstrap delta')
        grouped[v].append(d)
    output = iter(jsonlines(path)); reference = iter(jsonlines(reference_path))
    if not grouped:
        if next(output, None) is not None or next(reference, None) is not None:
            raise ValueError('Extra bootstrap records')
        return {'replicates': 0, 'visitors': 0, 'mean_delta': None, 'interval': None, 'reason': 'zero_queries'}
    visitors = sorted(grouped, key=int)
    sizes = [len(grouped[v]) for v in visitors]
    sums = [math.fsum(grouped[v]) for v in visitors]
    generator = np.random.Generator(np.random.PCG64(42)); deltas = []
    identity_keys = ('replicate', 'draw_sha256', 'query_denominator', 'rng_before', 'rng_after')
    for b in range(2000):
        watch(); before = generator.bit_generator.state
        drawn = generator.integers(0, len(visitors), size=len(visitors), dtype=np.int64).tolist()
        weights = Counter(drawn)
        denominator = sum(sizes[index] for index in drawn)
        delta = math.fsum(weights.get(i, 0) * sums[i] for i in range(len(visitors))) / denominator
        identity = {'replicate': b,
                    'draw_sha256': hashlib.sha256(struct.pack('<' + 'q' * len(drawn), *drawn)).hexdigest(),
                    'query_denominator': denominator, 'rng_before': before, 'rng_after': generator.bit_generator.state}
        actual = next(output, None); original = next(reference, None)
        if actual is None or original is None:
            raise ValueError('Missing D1 or reference bootstrap record')
        exact({k: original[k] for k in identity_keys}, identity, 'original bootstrap draw')
        close(actual, dict(identity, delta=delta), 'D1 bootstrap')
        deltas.append(delta)
    if next(output, None) is not None or next(reference, None) is not None:
        raise ValueError('Extra D1 or reference bootstrap record')
    ordered = sorted(deltas); interval = []
    for probability in (.025, .975):
        position = (len(ordered) - 1) * probability
        lower = math.floor(position); fraction = position - lower
        interval.append(ordered[lower] + fraction * (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]))
    return {'replicates': 2000, 'visitors': len(visitors),
            'mean_delta': math.fsum(d for _, d in records) / len(records), 'interval': interval, 'reason': None}


class ThreeArmOracle:
    def __init__(self, catalog):
        self.folds = {a: Fold(catalog) for a in ('P0', 'C1', 'D1')}
        self.differences = {name: {m: [] for m in METRICS} for name in ('D1_minus_C1', 'D1_minus_P0')}

    def add(self, q, ids, values, reachable, delta):
        for arm in self.folds:
            self.folds[arm].add(q, ids[arm], values[arm], reachable)
        for contrast in self.differences:
            for metric in METRICS:
                self.differences[contrast][metric].append(delta[contrast][metric])

    def result(self):
        arms = {a: fold.result() for a, fold in self.folds.items()}; n = arms['P0']['queries']
        contrasts = {}
        for name, control in (('D1_minus_C1', 'C1'), ('D1_minus_P0', 'P0')):
            delta = {m: math.fsum(values) / n if n else None for m, values in self.differences[name].items()}
            for metric in ('visitor_macro_ndcg', 'catalog_coverage'):
                x, y = arms['D1']['metrics'][metric], arms[control]['metrics'][metric]
                delta[metric] = x - y if x is not None and y is not None else None
            contrasts[name] = {'delta_metrics': delta}
        return arms, {'queries': n, 'visitors': arms['P0']['visitors'], 'comparisons': contrasts}


def _database(db, source, schemas, start, end, watch):
    db.execute('CREATE TABLE history(v TEXT,s INTEGER,t INTEGER,idx INTEGER,items TEXT,role TEXT,n INTEGER,PRIMARY KEY(v,s,t),UNIQUE(v,s,idx))')
    db.execute('CREATE TABLE membership(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
    db.execute('CREATE TABLE train_items(v TEXT,s INTEGER,t INTEGER,i TEXT,PRIMARY KEY(v,s,t,i))')
    for r in read_rows(source / 'baskets.csv', schemas['baskets.csv']):
        watch()
        if r['role'] not in ('warmup', 'train', 'validation'):
            continue
        v = r['visitorid']; num(v)
        s, t, index = num(r['session_start_ms']), num(r['query_ms']), num(r['basket_index'])
        items = json.loads(r['items'])
        if s > t or index < 1 or not isinstance(items, list) or not items or len(items) != len(set(items)):
            raise ValueError('Oracle invalid basket clock/index/members')
        for i in items:
            num(i)
        db.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?)', (v, s, t, index, r['items'], r['role'], len(items)))
        if r['role'] == 'train':
            if not start <= t < end:
                raise ValueError('Oracle fit clock')
            db.executemany('INSERT OR IGNORE INTO membership VALUES(?,?,?)', [(v, s, i) for i in items])
            db.executemany('INSERT INTO train_items VALUES(?,?,?,?)', [(v, s, t, i) for i in items])
    db.execute('CREATE TABLE support AS SELECT i,COUNT(*) AS n FROM membership GROUP BY i')
    # Preserve original indexes and role endpoints: no filtering-induced bridge.
    db.execute('''CREATE TABLE adjacent AS
        SELECT a.v,a.s,a.t AS ta,b.t AS tb FROM history a JOIN history b
          ON a.v=b.v AND a.s=b.s AND b.idx=a.idx+1
        WHERE a.role='train' AND b.role='train' AND b.t>a.t AND b.t-a.t<=1800000''')
    db.execute('CREATE UNIQUE INDEX adjacent_key ON adjacent(v,s,ta,tb)')
    db.execute('''CREATE TABLE emissions AS
        SELECT q.v,q.s,q.ta,q.tb,a.i AS a,b.i AS b FROM adjacent q
        JOIN train_items a ON a.v=q.v AND a.s=q.s AND a.t=q.ta
        JOIN train_items b ON b.v=q.v AND b.s=q.s AND b.t=q.tb WHERE a.i<>b.i''')
    db.execute('CREATE INDEX emissions_session ON emissions(v,s)')
    db.execute('CREATE TABLE session_edges AS SELECT DISTINCT v,s,a,b FROM emissions')
    db.execute('CREATE UNIQUE INDEX session_edges_key ON session_edges(v,s,a,b)')
    db.execute('CREATE TABLE edges AS SELECT a,b,COUNT(*) AS n FROM session_edges GROUP BY a,b')
    db.execute('CREATE UNIQUE INDEX edges_ab ON edges(a,b)')
    db.execute('CREATE INDEX edges_b ON edges(b)')
    db.execute("CREATE TABLE trainmeta AS SELECT v,s,COUNT(*) AS baskets,SUM(n) AS occurrences FROM history WHERE role='train' GROUP BY v,s")
    db.execute('CREATE UNIQUE INDEX trainmeta_key ON trainmeta(v,s)')
    db.execute('CREATE TABLE adjmeta AS SELECT v,s,COUNT(*) AS n FROM adjacent GROUP BY v,s')
    db.execute('CREATE UNIQUE INDEX adjmeta_key ON adjmeta(v,s)')
    db.execute('CREATE TABLE rawmeta AS SELECT v,s,COUNT(*) AS n FROM emissions GROUP BY v,s')
    db.execute('CREATE UNIQUE INDEX rawmeta_key ON rawmeta(v,s)')


def verify(folder, source, baseline, c1_reference, schemas, policy, parent, brute=False, watch=lambda: None):
    dbpath = folder / 'oracle.sqlite'
    if dbpath.exists():
        raise FileExistsError('Independent oracle database already exists; no replay')
    db = sqlite3.connect(dbpath); db.execute('PRAGMA temp_store=MEMORY')
    # SQL queries may run for longer than one Python iteration; keep resource checks cooperative.
    def progress():
        watch()
        return 0
    db.set_progress_handler(progress, 50000)
    rows_checked = Counter(); cells_checked = Counter()
    start, end = map(ms, (policy['comparison']['fit_start_inclusive_utc'], policy['comparison']['fit_end_exclusive_utc']))
    try:
        _database(db, source, schemas, start, end, watch)
        support = dict(db.execute('SELECT i,n FROM support'))
        counts = {}
        for r in read_rows(baseline / 'item_counts.csv', FIELDS['item_counts.csv']):
            i = r['itemid']; num(i); n = num(r['count'])
            if i in counts or n < 1:
                raise ValueError('Oracle invalid reference P0 counts')
            counts[i] = n
        if set(support) != set(counts) or any(support[i] > counts[i] for i in support):
            raise ValueError('Oracle shared support identity')
        if digest_file(folder / 'support.csv') != digest_file(c1_reference / 'support.csv'):
            raise ValueError('Oracle shared support bytes changed')
        digest = hashlib.sha256(f'D1_binary_session_directed_adjacent_association_v1\n{start},{end}\n'.encode())
        saved_support = iter(read_rows(folder / 'support.csv', ['itemid', 'support']))
        for i, n in sorted(support.items(), key=lambda pair: int(pair[0])):
            if next(saved_support, None) != {'itemid': i, 'support': str(n)}:
                raise ValueError('Oracle independently reconstructed S differs')
            digest.update(f'S,{i},{n}\n'.encode()); rows_checked['support.csv'] += 1; cells_checked['support.csv'] += 2
        if next(saved_support, None) is not None:
            raise ValueError('Extra shared support rows')
        db.execute('CREATE TABLE c1_edges(a TEXT,b TEXT,n INTEGER,PRIMARY KEY(a,b))')
        c1_mass = c1_count = 0
        for r in read_rows(c1_reference / 'pairs.csv', ['itemid_a', 'itemid_b', 'count']):
            a, b, n = r['itemid_a'], r['itemid_b'], num(r['count'])
            if not num(a) < num(b) or a not in support or b not in support or not 0 < n <= min(support[a], support[b]):
                raise ValueError('Oracle invalid reference C1 bound')
            db.execute('INSERT INTO c1_edges VALUES(?,?,?)', (a, b, n)); c1_mass += n; c1_count += 1
        actual_edges = iter(read_rows(folder / 'edges.csv', ['itemid_from', 'itemid_to', 'count'])); edge_mass = 0
        for a, b, n in db.execute('SELECT a,b,n FROM edges ORDER BY CAST(a AS INTEGER),CAST(b AS INTEGER)'):
            watch(); lower, upper = sorted((a, b), key=int)
            bound = db.execute('SELECT n FROM c1_edges WHERE a=? AND b=?', (lower, upper)).fetchone()
            if bound is None or a == b or not 0 < n <= bound[0] <= min(support[a], support[b]):
                raise ValueError('Oracle directed/C1 bound differs')
            if next(actual_edges, None) != {'itemid_from': a, 'itemid_to': b, 'count': str(n)}:
                raise ValueError('Oracle directed count cell differs')
            digest.update(f'D,{a},{b},{n}\n'.encode()); edge_mass += n
            rows_checked['edges.csv'] += 1; cells_checked['edges.csv'] += 3
        if next(actual_edges, None) is not None or edge_mass > 2 * c1_mass or rows_checked['edges.csv'] > 2 * c1_count:
            raise ValueError('Oracle directed count accounting differs')
        fit_id = digest.hexdigest(); actual_sessions = iter(jsonlines(folder / 'train_sessions.jsonl'))
        sessions = singletons = basket_n = occurrences = adj_n = raw_n = unique_n = 0
        cursor = db.execute('''SELECT m.v,m.s,m.i,t.baskets,t.occurrences,COALESCE(a.n,0),COALESCE(r.n,0)
            FROM membership m JOIN trainmeta t ON m.v=t.v AND m.s=t.s
            LEFT JOIN adjmeta a ON m.v=a.v AND m.s=a.s LEFT JOIN rawmeta r ON m.v=r.v AND m.s=r.s
            ORDER BY m.v,m.s,CAST(m.i AS INTEGER)''')
        for key, records in groupby(cursor, key=lambda r: r[:2]):
            watch(); records = list(records); ids = [r[2] for r in records]
            baskets, membership_n, adjacent, raw = records[0][3:]
            edges = [list(row) for row in db.execute('SELECT a,b FROM session_edges WHERE v=? AND s=? ORDER BY CAST(a AS INTEGER),CAST(b AS INTEGER)', key)]
            expected = {'key': list(key), 'items': ids, 'baskets': baskets, 'basket_memberships': membership_n,
                        'adjacent_pairs': adjacent, 'raw_directed_emissions': raw, 'edges': edges}
            exact(next(actual_sessions, None), expected, 'train session lineage')
            sessions += 1; singletons += len(ids) == 1; basket_n += baskets; occurrences += membership_n
            adj_n += adjacent; raw_n += raw; unique_n += len(edges)
            rows_checked['train_sessions.jsonl'] += 1; cells_checked['train_sessions.jsonl'] += 7
        if next(actual_sessions, None) is not None or edge_mass != unique_n:
            raise ValueError('Oracle session/directed accounting differs')
        audit = {'train_sessions': sessions, 'singleton_sessions': singletons, 'train_baskets': basket_n,
                 'basket_item_memberships': occurrences, 'distinct_session_item_memberships': sum(support.values()),
                 'eligible_adjacent_basket_pairs': adj_n, 'raw_directed_emissions': raw_n,
                 'distinct_session_directed_edges': unique_n, 'unique_directed_edges': rows_checked['edges.csv'],
                 'positive_support_items': len(support), 'start_ms': start, 'end_ms': end, 'fit_id': fit_id}
        close(json.loads((folder / 'fit_audit.json').read_text(encoding='utf-8')), audit)
        catalog = {}
        for r in read_rows(source / 'catalog.csv', schemas['catalog.csv']):
            i = r['itemid']; num(i)
            if i in catalog:
                raise ValueError('Oracle duplicate catalog ID')
            catalog[i] = num(r['first_view_ms'])
        if any(i not in catalog for i in support):
            raise ValueError('Oracle train item missing from catalog')
        first_times = sorted(catalog.values()); fallback = sorted(catalog, key=lambda i: (-counts.get(i, 0), int(i)))
        outgoing = {r[0] for r in db.execute('SELECT DISTINCT a FROM edges')}
        incoming = {r[0] for r in db.execute('SELECT DISTINCT b FROM edges')}
        main = ThreeArmOracle(catalog); conditional = ThreeArmOracle(catalog)
        groups = {f: {g: ThreeArmOracle(catalog) for g in names} for f, names in GROUPS.items()}
        outputs = iter(jsonlines(folder / 'queries.jsonl')); c1rows = iter(jsonlines(c1_reference / 'queries.jsonl'))
        rankrows = iter(read_rows(baseline / 'ranked_queries.csv', FIELDS['ranked_queries.csv']))
        metricrows = iter(read_rows(baseline / 'query_metrics.csv', FIELDS['query_metrics.csv']))
        slicerows = iter(read_rows(baseline / 'query_slices.csv', FIELDS['query_slices.csv']))
        records = []; roster = hashlib.sha256()
        diagnostics = {k: Counter() for k in ('history_size', 'supported_seeds', 'positive_evidence', 'fallback_reason', 'zero_fill_slots', 'outgoing_seeds', 'incoming_target_support')}
        implication = {k: 0 for k in ('C1_full_fallback_queries', 'D1_full_fallback_queries', 'C1_full_fallback_and_D1_positive', 'additional_D1_full_fallback_queries')}
        previous = None; val_start, val_end = map(ms, parent['time_roles']['validation'])
        for r in read_rows(source / 'queries.csv', schemas['queries.csv']):
            if r['role'] != 'validation':
                continue
            watch(); v = r['visitorid']; num(v)
            s, t, nt, index = num(r['session_start_ms']), num(r['query_ms']), num(r['next_view_ms']), num(r['basket_index'])
            key = (v, s, t)
            if previous is not None and key <= previous:
                raise ValueError('Oracle duplicate/unordered query')
            previous = key
            if not val_start <= t < nt < val_end or s > t or nt - t > 1800000 or t + 1800000 > val_end:
                raise ValueError('Oracle query clock')
            if any(r[k] != x for k, x in [('status', 'labelled'), ('next_role', 'validation'), ('next_in_session', '1'), ('mature', '1'), ('cross_role', '0')]):
                raise ValueError('Oracle invalid accepted validation state')
            current = db.execute('SELECT idx,n FROM history WHERE v=? AND s=? AND t=?', key).fetchone()
            if current is None or current[0] != index:
                raise ValueError('Oracle missing exact current basket')
            history = set()
            for row in db.execute('SELECT items FROM history WHERE v=? AND s=? AND t<=? AND idx<=? ORDER BY t', (v, s, t, index)):
                history.update(json.loads(row[0]))
            history = sorted(history, key=int)
            if not history:
                raise ValueError('Oracle empty history')
            score = defaultdict(Fraction); supported = sum(i in support for i in history)
            out_seeds = sum(i in outgoing for i in history)
            for i in history:
                if i not in support:
                    continue
                for j, n in db.execute('SELECT b,n FROM edges WHERE a=?', (i,)):
                    if catalog[j] < t:
                        score[j] += Fraction(n, support[i])
            if brute:
                eligible = [i for i in catalog if catalog[i] < t]
                ids = sorted(eligible, key=lambda j: (-score.get(j, Fraction()), -counts.get(j, 0), int(j)))[:10]
            else:
                ids = sorted(score, key=lambda j: (-score[j], -counts.get(j, 0), int(j)))[:10]
                for j in fallback:
                    if len(ids) >= 10:
                        break
                    if j not in ids and catalog[j] < t:
                        ids.append(j)
            candidate = bisect_left(first_times, t); ids = ids[:min(10, candidate)]
            evidence = len(score)
            reason = None if evidence else 'no_shared_supported_seed' if not supported else 'no_outgoing_seed' if not out_seeds else 'no_positive_causal_neighbor'
            fractions = [score.get(i, Fraction()) for i in ids]
            prediction = {'fit_id': fit_id, 'ids': ids, 'scores': [[x.numerator, x.denominator] for x in fractions],
                          'p0_counts': [counts.get(i, 0) for i in ids], 'candidate_count': candidate,
                          'supported_seeds': supported, 'outgoing_seeds': out_seeds, 'positive_candidates': evidence,
                          'zero_fill_slots': sum(x == 0 for x in fractions), 'fallback_reason': reason}
            targets = json.loads(r['target_items']); reachable = sum(i in catalog and catalog[i] < t for i in targets)
            if len(targets) != num(r['target_count']) or candidate != num(r['candidate_count']) or reachable != num(r['reachable_target_count']) or r['all_targets_reachable'] != str(int(reachable == len(targets))):
                raise ValueError('Oracle complete target/candidate denominator differs')
            pr, pm, ps, c1, actual = next(rankrows, None), next(metricrows, None), next(slicerows, None), next(c1rows, None), next(outputs, None)
            if any(x is None for x in (pr, pm, ps, c1, actual)):
                raise ValueError('Oracle missing three-way paired row')
            for row in (pr, pm, ps):
                if (row['visitorid'], num(row['session_start_ms']), num(row['query_ms'])) != key or row['role'] != 'validation':
                    raise ValueError('Oracle P0 complete key/order differs')
            for field, expected in [('key', list(key)), ('history', history), ('history_sha256', hashlib.sha256(encoded(history).encode()).hexdigest()), ('targets', targets), ('candidate_count', candidate), ('reachable_targets', reachable)]:
                exact(c1[field], expected, 'C1 ' + field)
            p0ids = json.loads(pr['top10_items']); t0, exact0 = terms(p0ids, targets)
            t1, exact1 = terms(c1['predictions']['C1']['ids'], targets); td, exactd = terms(ids, targets)
            expected0 = {k: float(pm[k]) for k in ('dcg', 'idcg', *METRICS)}
            expected0.update(target_count=num(pm['target_count']), hits=num(pm['hits']), first_hit_rank=num(pm['first_hit_rank']) if pm['first_hit_rank'] else None)
            pred0 = {'ids': p0ids, 'candidate_count': num(pr['candidate_count'])}
            exact(c1['predictions']['P0'], pred0, 'P0 rank identity'); exact(c1['terms']['P0'], expected0, 'P0 metrics identity')
            close(expected0, t0); close(c1['terms']['C1'], t1)
            exact(actual['predictions']['P0'], pred0, 'copied P0 rank')
            exact(actual['predictions']['C1'], c1['predictions']['C1'], 'copied C1 rank')
            exact(actual['terms']['P0'], expected0, 'copied P0 metric')
            exact(actual['terms']['C1'], c1['terms']['C1'], 'copied C1 metric')
            exact(actual['predictions']['D1'], prediction, 'D1 rational order')
            close(actual['terms']['D1'], td)
            # Score upper bound is independently checked for the complete D1-positive union,
            # not just its returned top ten. C1 reference output is never reranked.
            for j, dscore in score.items():
                cscore = Fraction()
                for i in history:
                    if i == j or i not in support:
                        continue
                    a, b = sorted((i, j), key=int)
                    found = db.execute('SELECT n FROM c1_edges WHERE a=? AND b=?', (a, b)).fetchone()
                    if found:
                        cscore += Fraction(found[0], support[i])
                if not 0 < dscore <= cscore:
                    raise ValueError('Oracle D1 score/C1 bound failed')
            if c1['predictions']['C1']['supported_seeds'] != supported or evidence > c1['predictions']['C1']['positive_candidates']:
                raise ValueError('Oracle shared seeds/positive set bound failed')
            train = num(r['train_view_events']); known = sum(i in support for i in targets)
            activity = '0' if not train else '1' if train == 1 else '2-5' if train <= 5 else '6+'
            if r['train_activity_slice'] != activity or r['visitor_seen_before_fit'] not in ('0', '1'):
                raise ValueError('Oracle diagnostic source malformed')
            memberships = {'visitor_history': 'seen' if r['visitor_seen_before_fit'] == '1' else 'new',
                           'current_basket': 'multiple' if current[1] > 1 else 'single',
                           'target_basket': 'multiple' if len(targets) > 1 else 'single', 'train_activity': activity,
                           'target_model': 'all_positive' if known == len(targets) else 'all_zero' if not known else 'mixed'}
            if any(ps[k] != value for k, value in memberships.items()):
                raise ValueError('Oracle inherited P0 slice differs')
            exact(c1['slices'], memberships, 'C1 slices')
            incoming_n = sum(i in incoming for i in targets)
            incoming_group = 'all' if incoming_n == len(targets) else 'none' if not incoming_n else 'mixed'
            delta = {name: {m: actual['terms']['D1'][m] - c1['terms'][control][m] for m in METRICS}
                     for name, control in (('D1_minus_C1', 'C1'), ('D1_minus_P0', 'P0'))}
            expected = {'key': list(key), 'history': history, 'history_sha256': hashlib.sha256(encoded(history).encode()).hexdigest(),
                        'targets': targets, 'candidate_count': candidate, 'reachable_targets': reachable,
                        'predictions': {'P0': pred0, 'C1': c1['predictions']['C1'], 'D1': prediction},
                        'terms': {'P0': expected0, 'C1': c1['terms']['C1'], 'D1': td}, 'delta': delta,
                        'slices': memberships, 'incoming_target_support': incoming_group}
            close(actual, expected)
            oq = {'v': v, 't': t, 'targets': targets}
            allids = {'P0': p0ids, 'C1': c1['predictions']['C1']['ids'], 'D1': ids}
            values = {'P0': exact0, 'C1': exact1, 'D1': exactd}
            main.add(oq, allids, values, reachable, delta)
            if reachable == len(targets):
                conditional.add(oq, allids, values, reachable, delta)
            for family, group in memberships.items():
                groups[family][group].add(oq, allids, values, reachable, delta)
            diagnostics['history_size'][str(len(history))] += 1; diagnostics['supported_seeds'][str(supported)] += 1
            diagnostics['outgoing_seeds'][str(out_seeds)] += 1; diagnostics['incoming_target_support'][incoming_group] += 1
            diagnostics['positive_evidence']['0' if not evidence else '1-9' if evidence < 10 else 'at_least_10'] += 1
            diagnostics['fallback_reason'][reason or 'positive_evidence'] += 1
            diagnostics['zero_fill_slots'][str(prediction['zero_fill_slots'])] += 1
            c1_fallback = not c1['predictions']['C1']['positive_candidates']; d1_fallback = not evidence
            implication['C1_full_fallback_queries'] += c1_fallback; implication['D1_full_fallback_queries'] += d1_fallback
            implication['C1_full_fallback_and_D1_positive'] += c1_fallback and not d1_fallback
            implication['additional_D1_full_fallback_queries'] += d1_fallback and not c1_fallback
            if c1_fallback and not d1_fallback:
                raise ValueError('Oracle C1 fallback implication failed')
            records.append((v, delta['D1_minus_C1']['ndcg'])); roster.update((encoded(list(key)) + '\n').encode())
            rows_checked['queries.jsonl'] += 1; cells_checked['queries.jsonl'] += 11
        if any(next(iterator, None) is not None for iterator in (outputs, rankrows, metricrows, slicerows, c1rows)):
            raise ValueError('Oracle extra three-way paired query')
        arms, paired = main.result(); conditional_arms, paired['conditional'] = conditional.result()
        floor = max(50, (paired['queries'] + 99) // 100); paired['slices'] = {}
        for arm in arms:
            arms[arm].update(conditional=conditional_arms[arm], support_floor_queries=floor, slices={})
        for family, buckets in groups.items():
            paired['slices'][family] = {}
            for arm in arms:
                arms[arm]['slices'][family] = {}
            for group, fold in buckets.items():
                ga, gp = fold.result(); n = gp['queries']
                flag = 'empty' if not n else 'descriptive_only' if n < floor else 'sufficient_query_count'
                gp['support'] = flag; paired['slices'][family][group] = gp
                for arm in arms:
                    ga[arm]['support'] = flag; arms[arm]['slices'][family][group] = ga[arm]
        original_aggregate = json.loads((c1_reference / 'aggregate.json').read_text(encoding='utf-8'))
        for arm in ('P0', 'C1'):
            close(arms[arm], original_aggregate['arms'][arm], 'reused ' + arm + ' complete aggregate')
        fixed = policy['fixed_validation']
        for k in ('queries', 'visitors', 'target_occurrences', 'reachable_target_occurrences', 'all_targets_reachable_queries', 'candidate_union_items', 'support_floor_queries'):
            if arms['D1'][k] != fixed[k]:
                raise ValueError('Oracle fixed denominator differs: ' + k)
        for family, group, key in [('visitor_history', 'new', 'new_visitor_queries'), ('current_basket', 'multiple', 'multi_item_current_queries'), ('target_basket', 'multiple', 'multi_item_target_queries')]:
            if arms['D1']['slices'][family][group]['queries'] != fixed[key]:
                raise ValueError('Oracle fixed slice differs')
        if {g: x['queries'] for g, x in arms['D1']['slices']['target_model'].items()} != fixed['target_model_query_counts']:
            raise ValueError('Oracle fixed shared support partitions differ')
        uncertainty = check_bootstrap(folder / 'bootstrap.jsonl', c1_reference / 'bootstrap.jsonl', records, watch)
        rows_checked['bootstrap.jsonl'] = uncertainty['replicates']; cells_checked['bootstrap.jsonl'] = uncertainty['replicates'] * 6
        diagnostics = {k: dict(v) for k, v in diagnostics.items()}; diagnostics['c1_full_fallback_implication'] = implication
        result = {'arms': arms, 'paired': paired, 'diagnostics': diagnostics, 'uncertainty': uncertainty, 'roster_sha256': roster.hexdigest()}
        close(json.loads((folder / 'aggregate.json').read_text(encoding='utf-8')), result)
        db.commit()
        return {'aggregate': result, 'rows': dict(rows_checked), 'top_level_cells': dict(cells_checked),
                'all_nested_JSON_values_checked': True,
                'ranking_oracle': 'full causal catalog sort' if brute else 'all SQL outgoing neighbors plus exact zero-score complement proof',
                'fit_audit': audit}
    finally:
        db.close()
