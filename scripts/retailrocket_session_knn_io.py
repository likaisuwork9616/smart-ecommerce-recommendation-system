"""Source-bound, validation-only K1 adapter. No control refit or reranking."""
from contextlib import ExitStack
import gc
import json

from scripts import retailrocket_session_knn as k
from scripts import retailrocket_session_knn_evaluation as evaluation
from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as old
from scripts import retailrocket_cooccurrence_io as inherited

ARTIFACTS = ('sessions.jsonl', 'postings.jsonl', 'train_sessions.jsonl', 'fit_audit.json',
             'queries.jsonl', 'bootstrap.jsonl', 'aggregate.json')
dump = k.encoded
exact = evaluation.exact


def jsonlines(path, watch=lambda: None):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            watch()
            value = json.loads(line)
            if type(value) is not dict:
                raise ValueError('Expected JSONL object: ' + str(path))
            yield value


def table(path, header, watch):
    values = {}
    for row in old.records(path, header):
        watch(); i = p.item(row[header[0]]); n = old.number(row[header[1]])
        if i in values or n <= 0:
            raise ValueError('Duplicate/nonpositive frozen support')
        values[i] = n
    return values


def baskets(source, config, roles, watch=lambda: None):
    if tuple(roles) not in (('train',), ('warmup', 'train', 'validation')):
        raise ValueError('Only fit or causal validation history roles')
    previous = None
    for row in old.records(source/'baskets.csv', config['schemas']['baskets.csv']):
        watch()
        if row['role'] not in roles:
            continue  # Exclude before decoding any item array or other row field.
        role = row['role']; lo, hi = config['role_windows_ms'][role]
        b = k.Basket(p.item(row['visitorid']), old.number(row['session_start_ms']),
                     old.number(row['query_ms']), role, old.number(row['basket_index']), old.array(row['items']))
        if not lo <= b.time < hi or b.session > b.time or b.index < 1:
            raise ValueError('Basket role/clock/index mismatch')
        if previous is not None and b.key() <= previous:
            raise ValueError('Duplicate/unordered accepted basket')
        previous = b.key()
        yield b


def queries(source, config, watch=lambda: None):
    lo, hi = config['validation_window_ms']
    for row in old.records(source/'queries.csv', config['schemas']['queries.csv']):
        watch()
        if row['role'] != 'validation': continue
        v = p.item(row['visitorid']); s = old.number(row['session_start_ms'])
        t, nt = old.number(row['query_ms']), old.number(row['next_view_ms'])
        if not lo <= t < nt < hi or nt-t > 1800000 or t+1800000 > hi or s > t:
            raise ValueError('Validation clock/horizon mismatch')
        for field, value in [('status','labelled'),('next_role','validation'),('next_in_session','1'),('mature','1'),('cross_role','0')]:
            if row[field] != value: raise ValueError('Invalid accepted validation state')
        targets = old.array(row['target_items']); train = old.number(row['train_view_events'])
        if len(targets) != old.number(row['target_count']) or p.activity(train) != row['train_activity_slice']:
            raise ValueError('Target/activity mismatch')
        yield p.Query(v,s,t,'validation',targets,0,old.boolean(row['visitor_seen_before_fit']),train,
            old.number(row['candidate_count']),old.number(row['reachable_target_count']),old.boolean(row['all_targets_reachable'])), old.number(row['basket_index'])


def references(p0, c1, d1, fits, counts, watch=lambda: None):
    streams = [iter(inherited.controls(p0)), iter(jsonlines(c1/'queries.jsonl', watch)),
               iter(jsonlines(d1/'queries.jsonl', watch))]
    previous = None
    while True:
        values = [next(s, None) for s in streams]
        if all(v is None for v in values):
            return
        if any(v is None for v in values):
            raise ValueError('Missing/extra original control query')
        (rank, metric, slices), one, three = values
        key = [rank['visitorid'], old.number(rank['session_start_ms']), old.number(rank['query_ms'])]
        if previous is not None and tuple(key) <= previous:
            raise ValueError('Duplicate/unordered original control')
        previous = tuple(key)
        if rank['role'] != 'validation' or rank['fit_id'] != fits['P0']:
            raise ValueError('Original P0 role/fit differs')
        pred0 = {'ids': json.loads(rank['top10_items']), 'candidate_count': old.number(rank['candidate_count'])}
        exact(json.loads(rank['top10_scores']), [counts.get(i, 0) for i in pred0['ids']], 'original P0 scores')
        terms0 = {m: float(metric[m]) for m in ('dcg', 'idcg', *p.METRICS)}
        terms0.update(target_count=old.number(metric['target_count']), hits=old.number(metric['hits']),
                      first_hit_rank=old.number(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
        for ref in (one, three):
            exact(ref['key'], key, 'original control key')
            exact(ref['predictions']['P0'], pred0, 'original P0 prediction')
            exact(ref['terms']['P0'], terms0, 'original P0 terms')
            exact(ref['slices'], {f: slices[f] for f in p.GROUPS}, 'P0 slices')
            if (ref['reachable_targets'] != old.number(metric['reachable_target_count'])
                    or old.boolean(metric['all_targets_reachable']) != (ref['reachable_targets'] == terms0['target_count'])):
                raise ValueError('Original P0 full target denominator')
        for field in ('key', 'history', 'history_sha256', 'targets', 'candidate_count', 'reachable_targets', 'slices'):
            exact(three[field], one[field], 'C1/D1 ' + field)
        for field in ('predictions', 'terms'):
            exact(three[field]['C1'], one[field]['C1'], 'original C1 ' + field)
        for arm in ('C1', 'D1'):
            if three['predictions'][arm]['fit_id'] != fits[arm]:
                raise ValueError('Original control fit differs: ' + arm)
        yield {f: three[f] for f in ('key', 'history', 'history_sha256', 'targets', 'candidate_count',
                                      'reachable_targets', 'predictions', 'terms', 'slices')} | {'control_fit_ids': dict(fits)}


def check_aggregate(result, config):
    fixed = config['fixed_validation']; main = result['main']['arms']['K1']
    for field in ('queries', 'visitors', 'target_occurrences', 'reachable_target_occurrences',
                  'all_targets_reachable_queries', 'candidate_union_items'):
        exact(main[field], fixed[field], 'fixed ' + field)
    exact(result['support_floor_queries'], fixed['support_floor_queries'], 'fixed support floor')
    for family, group, field in [('visitor_history','new','new_visitor_queries'),
                                 ('current_basket','multiple','multi_item_current_queries'),
                                 ('target_basket','multiple','multi_item_target_queries')]:
        exact(result['slices'][family][group]['queries'], fixed[field], 'fixed ' + field)
    exact({g: v['queries'] for g, v in result['slices']['target_model'].items()},
          fixed['target_model_query_counts'], 'fixed support slices')
    for arm, expected in config['expected_controls'].items():
        actual = dict(result['main']['arms'][arm], conditional=result['conditional']['arms'][arm],
                      support_floor_queries=result['support_floor_queries'], slices={})
        for family, groups in result['slices'].items():
            actual['slices'][family] = {g: dict(v['arms'][arm], support=v['support']) for g, v in groups.items()}
        inherited.close(actual, expected)


def build(folder, paths, config, watch=lambda: None):
    """Called only by the separately requested single-run dispatcher or artificial tests."""
    source, p0, c1, d1 = (paths[x] for x in ('dataset', 'P0', 'C1', 'D1'))
    if any((folder/name).exists() for name in ARTIFACTS):
        raise FileExistsError('Preserve existing/partial K1 artifacts')
    counts = table(p0/'item_counts.csv', old.HEADERS['item_counts.csv'], watch)
    support = table(c1/'support.csv', ['itemid', 'support'], watch)
    def catalog_rows():
        for r in old.records(source/'catalog.csv', config['schemas']['catalog.csv']):
            watch(); yield r['itemid'], old.number(r['first_view_ms'])
    catalog = p.Catalog(catalog_rows())
    with ExitStack() as stack:
        out = {name: stack.enter_context((folder/name).open('x', encoding='utf-8', newline='\n')) for name in ARTIFACTS}
        lineage = iter(jsonlines(c1/'train_sessions.jsonl', watch))
        def emit_session(row):
            exact(row, next(lineage, None), 'complete original C1 train lineage')
            out['train_sessions.jsonl'].write(dump(row)+'\n')
        model = k.fit(baskets(source, config, ('train',), watch), *config['train_window_ms'],
                      support, counts, emit_session, watch)
        if next(lineage, None) is not None:
            raise ValueError('Extra original C1 train lineage')
        for field, value in config['train_cost_audit'].items():
            exact(model.audit[field], value, 'accepted train cost ' + field)
        audit = dict(model.audit, fit_id=model.fit_id)
        out['fit_audit.json'].write(dump(audit)+'\n')
        for key in sorted(model.sessions, key=k.session_order):
            watch(); out['sessions.jsonl'].write(dump({'key': list(key), 'items': sorted(model.sessions[key], key=int)})+'\n')
        for i in sorted(model.postings, key=int):
            watch(); out['postings.jsonl'].write(dump({'itemid': i, 'sessions': [list(s) for s in model.postings[i]],
                                                       'support': support[i]})+'\n')
        expected = {key: config['fixed_validation'][key] for key in ('queries', 'visitors', 'target_occurrences',
                    'reachable_target_occurrences', 'all_targets_reachable_queries', 'candidate_union_items', 'support_floor_queries')}
        result = evaluation.evaluate(k.Ranker(model, counts, catalog, watch),
            baskets(source, config, ('warmup', 'train', 'validation'), watch), queries(source, config, watch),
            references(p0, c1, d1, config['control_fit_ids'], counts, watch), jsonlines(c1/'bootstrap.jsonl', watch),
            config['control_fit_ids'], config['validation_window_ms'], expected,
            lambda row: out['queries.jsonl'].write(dump(row)+'\n'),
            lambda row: out['bootstrap.jsonl'].write(dump(row)+'\n'), watch)
        check_aggregate(result, config)
        out['aggregate.json'].write(dump(result)+'\n')
    del model
    gc.collect()  # The independent reconstruction runs after the primary index is released.
    return {'fit_audit': audit, 'aggregate': result}
