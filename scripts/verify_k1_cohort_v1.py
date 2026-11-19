"""Check the August K1 roster against raw baskets and frozen control rankings."""
import argparse
from bisect import bisect_left
from collections import Counter
import hashlib
from itertools import groupby
import json
from pathlib import Path
import time

from scripts import run_retailrocket_session_knn_v1 as entry
from scripts.retailrocket_popularity_oracle import FIELDS, GROUPS, METRICS, num, read_rows
from scripts.retailrocket_session_knn_readback import dump, exact, ids, positive_table, rows


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT = ROOT / 'reports/stage12/retailrocket_session_knn_v1_validation_attempt.json'
PRIMARY = ROOT / entry.DEV
PATHS = {name: ROOT / path for name, path in entry.DIRECTORIES.items()}
SPEC = ROOT / entry.SPEC


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_once(path, result):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def verify_sources():
    attempt = read(ATTEMPT)
    entry.check([attempt['specification'], attempt['entry_acceptance']])
    verified = entry.verify_prepared()
    preserved = attempt['preservation']['execution_artifacts']
    exact(sorted(p.name for p in PRIMARY.iterdir()), sorted(Path(r['path']).name for r in preserved))
    entry.check(preserved)
    entry.gates()
    return dict(status='passed', prepared=verified, preserved_files=len(preserved),
                primary_sha256={Path(r['path']).name: r['sha256'] for r in preserved},
                entry_spec_sha256=sha(SPEC), attempt_sha256=sha(ATTEMPT))


def session_key(row):
    num(row['visitorid'])
    return row['visitorid'], num(row['session_start_ms'])


def basket_sessions(source, config):
    schema = config['schemas']['baskets.csv']
    windows = config['role_windows_ms']
    allowed = (r for r in read_rows(source / 'baskets.csv', schema) if r['role'] in windows)
    previous = None
    for key, group in groupby(allowed, session_key):
        if previous is not None and key <= previous:
            raise ValueError('Raw baskets out of session order')
        previous = key
        baskets = []
        for index, row in enumerate(group, 1):
            now = num(row['query_ms'])
            lo, hi = windows[row['role']]
            if not lo <= now < hi or now < key[1] or (baskets and now <= baskets[-1][0]):
                raise ValueError('Basket time or role mismatch')
            if index != num(row['basket_index']):
                raise ValueError('Nonconsecutive basket index')
            baskets.append((now, row['role'], ids(row['items'])))
        yield key, baskets


def hashed_rows(path, digest):
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            yield json.loads(line)


def check_query(raw, previous, baskets, lo, hi):
    visitor, start = session_key(raw)
    now, after, index = (num(raw[f]) for f in ('query_ms', 'next_view_ms', 'basket_index'))
    key = (visitor, start, now)
    if previous is not None and key <= previous:
        raise ValueError('Duplicate or unordered validation query')
    if not (start <= now and lo <= now < after < hi and after - now <= 1_800_000 and now + 1_800_000 <= hi):
        raise ValueError('Invalid query horizon')
    for field, expected in [('status', 'labelled'), ('next_role', 'validation'), ('next_in_session', '1'),
                            ('mature', '1'), ('cross_role', '0'), ('role', 'validation')]:
        exact(raw[field], expected)
    if not 1 <= index < len(baskets):
        raise ValueError('Missing current or next basket')
    current, successor = baskets[index - 1:index + 1]
    if current[:2] != (now, 'validation') or successor[:2] != (after, 'validation'):
        raise ValueError('Current or next basket identity mismatch')
    targets = ids(raw['target_items'])
    exact(sorted(targets, key=int), sorted(successor[2], key=int))
    return key, index, targets


def check_controls(controls, actual, identity, config, counts, catalog):
    rank, metric, slices, one, three = [next(stream, None) for stream in controls]
    if any(row is None for row in (rank, metric, slices, one, three)) or actual is None:
        raise ValueError('Missing paired row')
    key = identity['key']
    for row in (rank, metric, slices):
        exact([*session_key(row), num(row['query_ms'])], key)
        exact(row['role'], 'validation')
    p0 = json.loads(rank['top10_items'])
    exact(rank['fit_id'], config['control_fit_ids']['P0'])
    exact(json.loads(rank['top10_scores']), [counts.get(i, 0) for i in p0])
    p0pred = {'ids': p0, 'candidate_count': num(rank['candidate_count'])}
    p0terms = {m: float(metric[m]) for m in ('dcg', 'idcg', *METRICS)}
    p0terms.update(target_count=num(metric['target_count']), hits=num(metric['hits']),
                   first_hit_rank=num(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
    exact(num(metric['reachable_target_count']), identity['reachable_targets'])
    exact(num(metric['all_targets_reachable']), int(identity['reachable_targets'] == len(identity['targets'])))
    exact({f: slices[f] for f in GROUPS}, identity['slices'])
    for ref in (one, three, actual):
        for f, value in identity.items():
            exact(ref[f], value)
        exact(ref['predictions']['P0'], p0pred)
        exact(ref['terms']['P0'], p0terms)
    for arm in ('C1', 'D1'):
        exact(actual['predictions'][arm], three['predictions'][arm])
        exact(actual['terms'][arm], three['terms'][arm])
        exact(actual['predictions'][arm]['fit_id'], config['control_fit_ids'][arm])
    exact(one['predictions']['C1'], three['predictions']['C1'])
    exact(one['terms']['C1'], three['terms']['C1'])
    exact(sorted(actual), sorted(set(identity) | {'predictions', 'terms', 'delta'}))
    exact(sorted(actual['predictions']), ['C1', 'D1', 'K1', 'P0'])
    exact(sorted(actual['terms']), ['C1', 'D1', 'K1', 'P0'])
    for pred in actual['predictions'].values():
        if (pred['candidate_count'] != identity['candidate_count'] or
                len(pred['ids']) != min(10, identity['candidate_count']) or
                len(set(pred['ids'])) != len(pred['ids']) or
                any(i not in catalog or catalog[i] >= key[2] for i in pred['ids'])):
            raise ValueError('Incomplete, duplicate or unavailable recommendation')
    if actual['predictions']['K1']['fallback_reason'] is not None:
        exact(actual['predictions']['K1']['ids'], p0)


def verify_cohort(primary, paths, config, expected_sha):
    source = paths['dataset']
    catalog = {}
    for row in read_rows(source / 'catalog.csv', config['schemas']['catalog.csv']):
        num(row['itemid'])
        if row['itemid'] in catalog:
            raise ValueError('Duplicate catalog item')
        catalog[row['itemid']] = num(row['first_view_ms'])
    first_times = sorted(catalog.values())
    counts = positive_table(paths['P0'] / 'item_counts.csv', FIELDS['item_counts.csv'], lambda: None)
    support = positive_table(paths['C1'] / 'support.csv', ['itemid', 'support'], lambda: None)
    if counts.keys() != support.keys() or any(counts[i] < support[i] for i in support):
        raise ValueError('Popularity and training support disagree')
    controls = [iter(read_rows(paths['P0'] / f, FIELDS[f])) for f in
                ('ranked_queries.csv', 'query_metrics.csv', 'query_slices.csv')]
    controls += [iter(rows(paths[a] / 'queries.jsonl')) for a in ('C1', 'D1')]
    digest = hashlib.sha256()
    paired = iter(hashed_rows(primary / 'queries.jsonl', digest))
    sessions = iter(basket_sessions(source, config))
    source_session = next(sessions, None)
    validation = (r for r in read_rows(source / 'queries.csv', config['schemas']['queries.csv'])
                  if r['role'] == 'validation')
    roster = hashlib.sha256()
    visitors = set()
    summary = Counter()
    previous = None
    for sk, queries in groupby(validation, session_key):
        while source_session is not None and source_session[0] < sk:
            source_session = next(sessions, None)
        if source_session is None or sk != source_session[0]:
            raise ValueError('Missing session for development query')
        baskets = source_session[1]
        history = set()
        consumed = 0
        for raw in queries:
            key, index, targets = check_query(raw, previous, baskets, *config['validation_window_ms'])
            previous = key
            while consumed < index:
                history.update(baskets[consumed][2])
                consumed += 1
            ordered = sorted(history, key=int)
            t = key[2]
            reachable = sum(i in catalog and catalog[i] < t for i in targets)
            candidate = bisect_left(first_times, t)
            for field, value in [('target_count', len(targets)), ('reachable_target_count', reachable),
                                 ('candidate_count', candidate), ('all_targets_reachable', int(reachable == len(targets)))]:
                exact(num(raw[field]), value)
            train = num(raw['train_view_events'])
            activity = '0' if train == 0 else '1' if train == 1 else '2-5' if train <= 5 else '6+'
            exact(raw['train_activity_slice'], activity)
            if raw['visitor_seen_before_fit'] not in ('0', '1'):
                raise ValueError('Invalid visitor history flag')
            known = sum(i in support for i in targets)
            names = {'visitor_history': 'seen' if raw['visitor_seen_before_fit'] == '1' else 'new',
                     'current_basket': 'multiple' if len(baskets[index - 1][2]) > 1 else 'single',
                     'target_basket': 'multiple' if len(targets) > 1 else 'single', 'train_activity': activity,
                     'target_model': 'all_positive' if known == len(targets) else 'mixed' if known else 'all_zero'}
            identity = dict(key=list(key), history=ordered, history_sha256=hashlib.sha256(dump(ordered).encode()).hexdigest(),
                            targets=targets, candidate_count=candidate, reachable_targets=reachable, slices=names)
            check_controls(controls, next(paired, None), identity, config, counts, catalog)
            roster.update((dump(list(key)) + '\n').encode())
            visitors.add(key[0])
            summary.update(queries=1, target_occurrences=len(targets), reachable_target_occurrences=reachable,
                           all_targets_reachable_queries=int(reachable == len(targets)))
    if any(next(stream, None) is not None for stream in [*controls, paired]):
        raise ValueError('Extra paired row')
    summary['visitors'] = len(visitors)
    for f, value in summary.items():
        exact(value, config['fixed_validation'][f])
    exact(digest.hexdigest(), expected_sha)
    return dict(status='passed', **summary, queries_sha256=digest.hexdigest(), roster_sha256=roster.hexdigest(),
                paired_streams_eof=True, test_ranked_queries=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('sources_before', 'cohort', 'sources_after'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / ('k1_' + args.stage + '.json')
    if target.exists():
        raise FileExistsError(target)
    started = time.monotonic()
    if args.stage == 'cohort':
        before = read(args.out / 'k1_sources_before.json')
        exact(before['status'], 'passed')
        result = verify_cohort(PRIMARY, PATHS, read(SPEC)['configuration'], before['primary_sha256']['queries.jsonl'])
    else:
        result = verify_sources()
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    result['engine_sha256'] = sha(Path(__file__))
    write_once(target, result)
    print(args.stage, result['status'], result.get('queries', ''), result['elapsed_seconds'], flush=True)


if __name__ == '__main__':
    main()
