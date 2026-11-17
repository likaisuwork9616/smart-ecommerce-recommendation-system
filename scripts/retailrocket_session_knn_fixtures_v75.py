"""Sealed V75 artificial inputs and independent goldens; preparation only.

This module is never imported by a candidate worker. Its source serializer is
adapted from the frozen V1 synthetic tests, preserving that fixture vocabulary.
Call only after the preparation sources have been archived. No real data API.
"""
from collections import Counter
from copy import deepcopy
import csv
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

from scripts import retailrocket_popularity as p
from scripts import retailrocket_popularity_io as old
from scripts import retailrocket_cooccurrence as c
from scripts import retailrocket_directed as d
from scripts import retailrocket_session_knn_io as adapter
from scripts import retailrocket_session_knn_readback as oracle
from scripts import retailrocket_session_knn_readback_v2 as reference_v2
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import run_retailrocket_session_knn_v1 as entry
from tests.test_retailrocket_session_knn import fixture_inputs

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.runtime' / 'v75'
PROFILES = {'F-small': (7, 6), 'F-long': (129, 3), 'F-edge': (1, 1)}


def _inputs(profile):
    if profile != 'F-long':
        return fixture_inputs(profile == 'F-edge')
    original = fixture_inputs(False)
    rows = [b for b in original[0] if b.role == 'train']
    raw_queries = []
    for visitor, count in zip(('90', '91', '92'), (70, 40, 19)):
        for index in range(count + 1):
            at = 110 + index * 2
            rows.append(c.Basket(visitor, 105, at, 'validation', index + 1,
                                 (str(index % 4 + 1),)))
            if index < count:
                raw_queries.append((visitor, 105, at, index + 1,
                                    (str((index + 1) % 4 + 1),)))
    rows.sort(key=lambda basket: basket.key())
    catalog = original[3]
    cat = p.Catalog(catalog)
    counts = dict(Counter(item for b in rows if b.role == 'train' for item in b.items))
    cm = c.fit(rows, 10, 100, counts)
    dm = d.fit(rows, 10, 100, cm.support, cm.pairs, counts)
    pm = p.Model(counts, 'synthetic_P0', {})
    rankers = {'P0': p.Ranker(pm, cat), 'C1': c.Ranker(cm, counts, cat),
               'D1': d.Ranker(dm, counts, cat)}
    fits = {'P0': pm.fit_id, 'C1': cm.fit_id, 'D1': dm.fit_id}
    references, queries, pairs = [], [], []
    for visitor, session, at, index, targets in sorted(raw_queries):
        seen = [b for b in rows if b.visitor == visitor and b.session == session and b.time <= at]
        history = sorted({item for b in seen for item in b.items}, key=int)
        current = next(b for b in seen if b.time == at)
        train_views = sum(len(b.items) for b in rows if b.visitor == visitor and b.role == 'train')
        reachable = sum(cat.contains(item, at) for item in targets)
        query = p.Query(visitor, session, at, 'validation', targets, len(current.items),
                        train_views > 0, train_views, cat.size(at), reachable,
                        reachable == len(targets))
        predictions = {arm: ranker.rank(at) if arm == 'P0' else ranker.rank(at, history)
                       for arm, ranker in rankers.items()}
        predictions['P0'] = {key: predictions['P0'][key] for key in ('ids', 'candidate_count')}
        terms = {arm: p.metric_terms(prediction['ids'], targets)
                 for arm, prediction in predictions.items()}
        references.append({'key': list(query.key()), 'history': history,
            'history_sha256': hashlib.sha256(adapter.dump(history).encode()).hexdigest(),
            'targets': list(targets), 'candidate_count': cat.size(at),
            'reachable_targets': reachable, 'predictions': predictions, 'terms': terms,
            'slices': p.slice_names(query, counts), 'control_fit_ids': dict(fits)})
        queries.append((query, index))
        pairs.append((visitor, terms['C1']['ndcg'] - terms['P0']['ndcg']))
    draws = []
    c.bootstrap(pairs, draws.append)
    expected = {'queries': len(queries), 'visitors': 3,
        'target_occurrences': sum(len(q.targets) for q, _ in queries),
        'reachable_target_occurrences': sum(q.reachable_count for q, _ in queries),
        'all_targets_reachable_queries': sum(q.all_reachable for q, _ in queries),
        'candidate_union_items': cat.size(max(q.query_ms for q, _ in queries)),
        'support_floor_queries': 50}
    return rows, counts, dict(cm.support), catalog, queries, references, draws, fits, expected


def write_csv(path, header, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, header, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def write_lines(path, values):
    path.write_text(''.join(adapter.dump(value) + '\n' for value in values), encoding='utf-8')


def _write_sources(base, profile):
    root=Path(base);root.mkdir(parents=True, exist_ok=False)
    paths={key:root/key for key in ('dataset','P0','C1','D1')}
    for folder in paths.values():folder.mkdir()
    raw,counts,support,catalog,queries,refs,draws,fits,expected=_inputs(profile)
    factor=10000
    baskets=[replace(b,session=b.session*factor,time=b.time*factor) for b in raw]
    queries=[(replace(q,session_start_ms=q.session_start_ms*factor,query_ms=q.query_ms*factor),index) for q,index in queries]
    catalog=[(i,t*factor) for i,t in catalog];cat=p.Catalog(catalog)
    lineage=[]
    cm=c.fit(baskets,10*factor,100*factor,counts,
        lambda key,items,n,o:lineage.append({'key':list(key),'items':items,'baskets':n,'basket_memberships':o}))
    dm=d.fit(baskets,10*factor,100*factor,cm.support,cm.pairs,counts)
    fits=dict(fits,C1=cm.fit_id,D1=dm.fit_id)
    for ref in refs:
        ref['key'][1]*=factor;ref['key'][2]*=factor
        ref['predictions']['C1']['fit_id']=cm.fit_id;ref['predictions']['D1']['fit_id']=dm.fit_id
        ref['control_fit_ids']=dict(fits)
    schemas=entry.read('reports/stage8/retailrocket_build_v1_specification.json')['schemas']
    bvalues=[dict(visitorid=b.visitor,session_start_ms=b.session,query_ms=b.time,role=b.role,basket_index=b.index,
                  items=adapter.dump(list(b.items)),source_records='[]',context_item_occurrences=len(b.items)) for b in baskets]
    # Poison every non-role field, including timestamps: neither path may decode test/tail payloads.
    for role in ('reserved_test','tail'):
        bvalues.append(dict.fromkeys(schemas['baskets.csv'],'POISON')|{'role':role})
    write_csv(paths['dataset']/'baskets.csv',schemas['baskets.csv'],bvalues)
    qvalues=[]
    for q,index in queries:
        successor=min((b for b in baskets if b.visitor==q.visitorid and b.session==q.session_start_ms and b.time>q.query_ms),key=lambda b:b.time)
        qvalues.append(dict(visitorid=q.visitorid,session_start_ms=q.session_start_ms,query_ms=q.query_ms,role='validation',
            basket_index=index,context_item_occurrences=q.current_size,next_view_ms=successor.time,next_role='validation',
            next_in_session='1',mature='1',cross_role='0',status='labelled',candidate_count=q.candidate_count,
            target_items=adapter.dump(list(q.targets)),target_count=len(q.targets),reachable_target_count=q.reachable_count,
            all_targets_reachable=str(int(q.all_reachable)),visitor_seen_before_fit=str(int(q.visitor_seen)),
            targets_seen_before_fit='unused',train_view_events=q.train_views,train_activity_slice=p.activity(q.train_views)))
    for role in ('train','reserved_test','tail'):
        qvalues.append(dict.fromkeys(schemas['queries.csv'],'POISON')|{'role':role})
    write_csv(paths['dataset']/'queries.csv',schemas['queries.csv'],qvalues)
    write_csv(paths['dataset']/'catalog.csv',schemas['catalog.csv'],[{'itemid':i,'first_view_ms':t} for i,t in catalog])
    write_csv(paths['P0']/'item_counts.csv',old.HEADERS['item_counts.csv'],[{'itemid':i,'count':n} for i,n in counts.items()])
    p0rows={name:[] for name in ('ranked_queries.csv','query_metrics.csv','query_slices.csv')}
    for (q,index),ref in zip(queries,refs):
        pred=dict(ref['predictions']['P0'],fit_id=fits['P0'],scores=[counts.get(i,0) for i in ref['predictions']['P0']['ids']])
        for name,row in old.artifact_rows(q,pred,ref['terms']['P0'],ref['slices']).items():
            p0rows[name].append({field:old.cell(value) for field,value in zip(old.HEADERS[name],row)})
    for name,values in p0rows.items():write_csv(paths['P0']/name,old.HEADERS[name],values)
    write_csv(paths['C1']/'support.csv',['itemid','support'],[{'itemid':i,'support':n} for i,n in support.items()])
    write_lines(paths['C1']/'train_sessions.jsonl',lineage)
    c1rows=[];d1rows=[]
    for ref in refs:
        row={k:deepcopy(v) for k,v in ref.items() if k!='control_fit_ids'}
        d1rows.append(row)
        one=deepcopy(row);one['predictions'].pop('D1');one['terms'].pop('D1');c1rows.append(one)
    write_lines(paths['C1']/'queries.jsonl',c1rows);write_lines(paths['D1']/'queries.jsonl',d1rows)
    write_lines(paths['C1']/'bootstrap.jsonl',draws)
    for arm in ('P0','C1','D1'):(paths[arm]/'fit_audit.json').write_text(adapter.dump({'fit_id':fits[arm]}),encoding='utf-8')
    controls={}
    fixed=dict(expected,new_visitor_queries=sum(not q.visitor_seen for q,_ in queries),
        multi_item_current_queries=sum(q.current_size>1 for q,_ in queries),multi_item_target_queries=sum(len(q.targets)>1 for q,_ in queries),
        target_model_query_counts={g:sum(ref['slices']['target_model']==g for ref in refs) for g in p.GROUPS['target_model']})
    for arm in ('P0','C1','D1'):
        folds={'main':p.Aggregate(cat),'conditional':p.Aggregate(cat)}
        groups={f:{g:p.Aggregate(cat) for g in names} for f,names in p.GROUPS.items()}
        for (q,_),ref in zip(queries,refs):
            args=(q,ref['predictions'][arm],ref['terms'][arm],q.reachable_count)
            folds['main'].add(*args)
            if q.all_reachable:folds['conditional'].add(*args)
            for f,g in ref['slices'].items():groups[f][g].add(*args)
        control=dict(folds['main'].result(),conditional=folds['conditional'].result(),support_floor_queries=50,slices={})
        for f,buckets in groups.items():
            control['slices'][f]={}
            for g,fold in buckets.items():
                value=fold.result();control['slices'][f][g]=dict(value,support='empty' if not value['queries'] else 'descriptive_only' if value['queries']<50 else 'sufficient_query_count')
        controls[arm]=control
    cost={key:cm.audit[key] for key in ('train_sessions','singleton_sessions','train_baskets','basket_item_memberships','distinct_session_item_memberships','positive_support_items')}
    cost.update(maximum_session_items=max(len(r['items']) for r in lineage),maximum_posting_size=max(support.values()))
    config={'schemas':schemas,'train_window_ms':[10*factor,100*factor],
        'validation_window_ms':[100*factor,1000*factor],
        'validation_window_utc':[datetime.fromtimestamp(t*factor/1000,timezone.utc).isoformat() for t in (100,1000)],
        'role_windows_ms':{'warmup':[0,10*factor],'train':[10*factor,100*factor],'validation':[100*factor,1000*factor]},
        'control_fit_ids':fits,'fixed_validation':fixed,'expected_controls':controls,'train_cost_audit':cost}
    (root/'configuration.json').write_text(adapter.dump(config)+'\n',encoding='utf-8')
    return root,paths,config


def prepare_bundle(destination, profile='F-small'):
    """Create one fresh, bounded artificial bundle and freeze V1/V2 goldens.

    There is deliberately no overwrite, arbitrary-source or candidate argument.
    The caller separately seals the returned manifest before candidate admission.
    """
    if profile not in PROFILES:
        raise ValueError('Unknown artificial profile')
    destination = Path(destination).resolve()
    expected_root = (PRIVATE / 'fixtures' / profile).resolve()
    if destination != expected_root or destination.exists() or not destination.is_relative_to(ROOT.resolve()):
        raise ValueError('Only a fresh fixed V75 artificial destination is allowed')
    for parent in (ROOT / '.runtime', PRIVATE, PRIVATE / 'fixtures'):
        if parent.exists() and (parent.is_symlink() or
                               getattr(parent, 'is_junction', lambda: False)()):
            raise ValueError('Artificial fixture parent cannot be a link or junction')
    root, paths, config = _write_sources(destination, profile)
    config['synthetic_acceptance_only'] = True
    (root / 'configuration.json').write_text(adapter.dump(config) + '\n', encoding='utf-8')
    wanted = PROFILES[profile]
    if (config['fixed_validation']['queries'], config['fixed_validation']['visitors']) != wanted:
        raise ValueError('Artificial fixture cardinality differs')
    primary = root / 'primary'
    primary.mkdir()
    adapter.build(primary, paths, config)
    reference = oracle.verify(primary, paths, config)
    # The frozen V2 verifier, not V75, creates expected complete ledger payloads.
    source_names = [path.relative_to(root).as_posix() for path in sorted(root.rglob('*'))
                    if path.is_file()]
    binding = {'sources': cp.bind_sources(root, source_names), 'configuration': config,
               'method': 'v75_artificial_golden_from_frozen_v2'}
    golden_store = PRIVATE / 'reference-evidence' / profile
    store = cp.CheckpointStore.create(golden_store, binding,
        (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(), 900,
        source_root=root, expected_queries=wanted[0],
        required_stages=('reconstruction', 'queries', 'global', 'bootstrap'), chunk_queries=64)
    with store.writer():
        result = reference_v2.verify(primary, paths, config, store)
    if result['aggregate'] != reference['aggregate']:
        raise ValueError('Frozen V1/V2 artificial aggregate mismatch')
    records_path = root / 'golden_records.jsonl'
    with records_path.open('xb') as stream:
        for record in store.iter_records():
            stream.write(cp.encoded(record))
    (root / 'reference.json').write_text(adapter.dump(reference) + '\n', encoding='utf-8')
    descriptors = []
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        role = ('golden' if relative == 'golden_records.jsonl' else
                'reference' if relative == 'reference.json' else
                'configuration' if relative == 'configuration.json' else relative.split('/')[0])
        descriptors.append(dict(cp.descriptor(root, relative), role=role))
    manifest = {'schema': 'v75_artificial_bundle', 'fixture_id': profile,
        'profile': 'synthetic_only', 'expected_queries': wanted[0], 'expected_visitors': wanted[1],
        'bootstrap_replicates': 2000, 'configuration': config,
        'paths': {name: path.relative_to(root).as_posix() for name, path in paths.items()},
        'primary': 'primary', 'golden_records': 'golden_records.jsonl', 'reference': 'reference.json',
        'sources': descriptors, 'generator': 'scripts/retailrocket_session_knn_fixtures_v75.py',
        'oracle': 'scripts/retailrocket_session_knn_readback.py',
        'golden_oracle': 'scripts/retailrocket_session_knn_readback_v2.py',
        'synthetic_only': True, 'real_execution_enabled': False}
    (root / 'manifest.json').write_text(adapter.dump(manifest) + '\n', encoding='utf-8')
    return {'root': root, 'paths': paths, 'config': config, 'primary': primary,
            'reference': reference, 'golden_records_path': records_path, 'manifest': manifest}
