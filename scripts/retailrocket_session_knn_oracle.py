"""Independent SQL train membership and exhaustive K1 oracle.

Does not import K1 production, its evaluator, fit, index or ranking helpers.
Reuses only previously frozen Decimal metric and cluster-replay oracles.
"""
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
import sqlite3

from scripts.retailrocket_popularity_oracle import terms, Fold, close, num, GROUPS, METRICS
from scripts.retailrocket_directed_oracle import check_bootstrap


def dump(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def exact(actual,expected):
    if json.dumps(actual,sort_keys=True,allow_nan=False) != json.dumps(expected,sort_keys=True,allow_nan=False):
        raise ValueError('Independent exact value mismatch')


def reconstruct(rows,start,end,db_path=':memory:'):
    db = sqlite3.connect(db_path)
    try:
        db.execute('CREATE TABLE b(v TEXT,s INTEGER,t INTEGER,k INTEGER,n INTEGER,PRIMARY KEY(v,s,t),UNIQUE(v,s,k))')
        db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        for b in rows:
            if b['role'] != 'train':
                continue
            num(b['visitor']); s,t,index = b['session'],b['time'],b['index']
            if (any(type(n) is not int for n in (s,t,index)) or not 0 <= s <= t
                    or not start <= t < end or index < 1):
                raise ValueError('Oracle train clock/index')
            ids = b['items']
            if not ids or len(set(ids)) != len(ids):
                raise ValueError('Oracle basket duplicates/empty')
            for i in ids:
                num(i)
            db.execute('INSERT INTO b VALUES(?,?,?,?,?)',(b['visitor'],s,t,index,len(ids)))
            db.executemany('INSERT OR IGNORE INTO m VALUES(?,?,?)',[(b['visitor'],s,i) for i in ids])
        sessions = {}
        for v,s,i in db.execute('SELECT v,s,i FROM m ORDER BY v,s,i'):
            sessions.setdefault((v,s),set()).add(i)
        support = dict(db.execute('SELECT i,COUNT(*) FROM m GROUP BY i'))
        postings = {i:[] for i in support}
        for v,s,i in db.execute('SELECT v,s,i FROM m'):
            postings[i].append((v,s))
        for i in postings:
            postings[i].sort(key=lambda x:(int(x[0]),x[1]))
        n,occurrences = db.execute('SELECT COUNT(*),COALESCE(SUM(n),0) FROM b').fetchone()
        audit = {'start_ms':start,'end_ms':end,'train_sessions':len(sessions),
                 'singleton_sessions':sum(len(v)==1 for v in sessions.values()),'train_baskets':n,
                 'basket_item_memberships':occurrences,'distinct_session_item_memberships':sum(support.values()),
                 'positive_support_items':len(support),'maximum_session_items':max(map(len,sessions.values()),default=0),
                 'maximum_posting_size':max(support.values(),default=0)}
        h = hashlib.sha256(('K1_Jaccard_exact_session_k500_v1\n'+str(start)+','+str(end)+'\n').encode())
        ordered = sorted(sessions,key=lambda x:(int(x[0]),x[1]))
        for key in ordered:
            h.update((dump([list(key),sorted(sessions[key],key=int)])+'\n').encode())
        payload = {'fit_id':h.hexdigest(),'audit':audit,
            'sessions':[{'key':list(key),'items':sorted(sessions[key],key=int)} for key in ordered],
            'postings':[{'itemid':i,'sessions':[list(s) for s in postings[i]],'support':support[i]} for i in sorted(support,key=int)]}
        lineage = []
        for v,s,n,o in db.execute('SELECT v,s,COUNT(*),SUM(n) FROM b GROUP BY v,s ORDER BY v,s'):
            lineage.append({'key':[v,s],'items':sorted(sessions[v,s],key=int),'baskets':n,'basket_memberships':o})
        db.commit()
        return sessions,support,payload,lineage
    finally:
        db.close()


def predict(sessions,support,fit_id,counts,catalog,time,history,current):
    # Enumerate EVERY session, including zero-overlap rows, without an inverted index.
    h = set(history); pool = []; raw_visits = 0; excluded = 0
    for key,items in sessions.items():
        overlap = len(h.intersection(items)); raw_visits += overlap
        if key == tuple(current):
            excluded += int(overlap > 0)
            continue
        if overlap:
            union = len(h.union(items))
            pool.append((key,overlap,union,Fraction(overlap,union)))
    digest = hashlib.sha256()
    for key,x,y,_ in sorted(pool,key=lambda row:(int(row[0][0]),row[0][1])):
        digest.update((dump([list(key),x,y])+'\n').encode())
    pool.sort(key=lambda row:(-row[3],int(row[0][0]),row[0][1]))
    selected = pool[:500]
    boundary = selected[-1][3] if len(selected)==500 else None
    total_ties = sum(row[3]==boundary for row in pool) if boundary is not None else 0
    removed_ties = sum(row[3]==boundary for row in pool[500:]) if boundary is not None else 0
    candidates = [i for i,t in catalog.items() if t < time]
    # Full-catalog score summation is independent of the sparse production votes/fill.
    scores = {i:sum((sim for key,_,_,sim in selected if i in sessions[key]),Fraction(0)) for i in candidates}
    order = sorted(candidates,key=lambda i:(-scores[i],-counts.get(i,0),int(i)))[:10]
    positive = sum(value>0 for value in scores.values())
    supported = sum(i in support for i in h)
    reason = None
    if positive == 0:
        if supported == 0:
            reason = 'no_supported_seed'
        elif not pool and excluded:
            reason = 'only_self_session_overlap'
        elif not pool:
            reason = 'no_eligible_positive_neighbor'
        else:
            reason = 'no_positive_causal_vote'
    return {'fit_id':fit_id,'ids':order,'scores':[[scores[i].numerator,scores[i].denominator] for i in order],
            'p0_counts':[counts.get(i,0) for i in order],'candidate_count':len(candidates),'history_size':len(h),
            'supported_seeds':supported,'unknown_seeds':len(h)-supported,'raw_posting_visits':raw_visits,
            'current_session_excluded':excluded,'eligible_neighbors':len(pool),'neighbor_pool_sha256':digest.hexdigest(),
            'selected_neighbors':[{'key':list(key),'intersection':a,'union':b,'similarity':[s.numerator,s.denominator]}
                                  for key,a,b,s in selected],
            'selected_neighbor_count':len(selected),'boundary_similarity':None if boundary is None else [boundary.numerator,boundary.denominator],
            'boundary_ties_total':total_ties,'boundary_ties_excluded':removed_ties,
            'vote_memberships':sum(len(sessions[key]) for key,_,_,_ in selected),'positive_candidates':positive,
            'zero_fill_slots':sum(scores[i]==0 for i in order),'fallback_reason':reason}


def jsonlines(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def verify_case(folder, persist=False):
    """Read saved synthetic inputs/outputs completely; never open real datasets."""
    source = json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
    if source['kind'] != 'synthetic_K1_acceptance':
        raise ValueError('This oracle harness accepts synthetic evidence only')
    sessions,support,payload,lineage = reconstruct(source['baskets'],*source['train_window'],folder/'oracle.sqlite' if persist else ':memory:')
    exact(json.loads((folder/'model.json').read_text(encoding='utf-8')),payload)
    exact(list(jsonlines(folder/'train_sessions.jsonl')),lineage)
    exact({i:int(n) for i,n in source['support'].items()},support)
    catalog = dict(source['catalog']); counts = source['counts']
    actual_rows = iter(jsonlines(folder/'queries.jsonl')); refs = iter(source['references'])
    scopes = {'main':[],'conditional':[]}
    for family,groups in GROUPS.items():
        for group in groups:
            scopes[family+'/'+group] = []
    diagnostics = {name:Counter() for name in ('history_size','unknown_seeds','eligible_neighbors','current_session_excluded',
        'selected_neighbor_count','boundary_ties_excluded','positive_candidates','zero_fill_slots','fallback_reason')}
    cross = Counter(); roster = hashlib.sha256(); deltas = []; checked = 0; exact_scalars = 0
    for raw,index in source['queries']:
        key = [raw['visitorid'],raw['session_start_ms'],raw['query_ms']]
        matching = [b for b in source['baskets'] if b['visitor']==key[0] and b['session']==key[1] and b['time']<=key[2]
                    and b['role'] in ('warmup','train','validation')]
        matching.sort(key=lambda b:b['time'])
        if not matching or matching[-1]['time']!=key[2] or matching[-1]['index']!=index:
            raise ValueError('Oracle missing current basket')
        history = sorted({i for b in matching for i in b['items']},key=int)
        pred = predict(sessions,support,payload['fit_id'],counts,catalog,key[2],history,key[:2])
        ref = next(refs); actual = next(actual_rows,None)
        if actual is None:
            raise ValueError('Oracle missing K1 row')
        exact(ref['key'],key); exact(ref['control_fit_ids'],source['control_fit_ids'])
        exact(ref['history'],history); exact(ref['targets'],raw['targets'])
        predictions = dict(ref['predictions'],K1=pred)
        values = {}; decimals = {}
        for arm in ('P0','C1','D1','K1'):
            independent,precise = terms(predictions[arm]['ids'],raw['targets'])
            close(actual['terms'][arm],independent,arm+' independent Decimal metric')
            decimals[arm] = precise
            if arm != 'K1':
                exact(actual['terms'][arm],ref['terms'][arm])
                values[arm] = ref['terms'][arm]
            else:
                # Binary64 after independent Decimal verification is the contracted delta input.
                values[arm] = actual['terms'][arm]
        current_size = len(matching[-1]['items']); known = sum(i in support for i in raw['targets'])
        train = raw['train_views']
        names = {'visitor_history':'seen' if raw['visitor_seen'] else 'new',
                 'current_basket':'multiple' if current_size>1 else 'single',
                 'target_basket':'multiple' if len(raw['targets'])>1 else 'single',
                 'train_activity':'0' if train==0 else '1' if train==1 else '2-5' if train<=5 else '6+',
                 'target_model':'all_positive' if known==len(raw['targets']) else 'all_zero' if known==0 else 'mixed'}
        reachable = sum(i in catalog and catalog[i]<key[2] for i in raw['targets'])
        delta = {'K1_minus_'+arm:{m:values['K1'][m]-values[arm][m] for m in METRICS} for arm in ('C1','P0','D1')}
        expected = {'key':key,'history':history,'history_sha256':hashlib.sha256(dump(history).encode()).hexdigest(),
                    'targets':raw['targets'],'candidate_count':sum(t<key[2] for t in catalog.values()),
                    'reachable_targets':reachable,'predictions':predictions,'terms':values,'delta':delta,'slices':names}
        exact(actual,expected)
        def scalar_count(value):
            if isinstance(value,dict): return sum(scalar_count(v) for v in value.values())
            if isinstance(value,list): return sum(scalar_count(v) for v in value)
            return 1
        exact_scalars += scalar_count(expected)
        row = (raw,predictions,decimals,delta,reachable)
        scopes['main'].append(row)
        if reachable==len(raw['targets']): scopes['conditional'].append(row)
        for f,g in names.items(): scopes[f+'/'+g].append(row)
        for name in diagnostics:
            diagnostics[name][str(pred[name]) if name!='fallback_reason' else pred[name] or 'positive_evidence'] += 1
        cross[dump([pred['fallback_reason'] is not None,predictions['C1']['positive_candidates']==0,
                    predictions['D1']['positive_candidates']==0,names['target_model']])] += 1
        roster.update((dump(key)+'\n').encode()); deltas.append((key[0],delta['K1_minus_C1']['ndcg'])); checked += 1
    if next(actual_rows,None) is not None or next(refs,None) is not None:
        raise ValueError('Oracle extra rows')
    def summarize(rows):
        folds = {a:Fold(catalog) for a in ('P0','C1','D1','K1')}
        for q,pred,values,delta,reachable in rows:
            for arm in folds:
                folds[arm].add({'v':q['visitorid'],'t':q['query_ms'],'targets':q['targets']},pred[arm]['ids'],values[arm],reachable)
        arms = {a:f.result() for a,f in folds.items()}; comparisons = {}
        for control in ('C1','P0','D1'):
            key = 'K1_minus_'+control
            values = {m:math.fsum(row[3][key][m] for row in rows)/len(rows) if rows else None for m in METRICS}
            for m in ('visitor_macro_ndcg','catalog_coverage'):
                x,y = arms['K1']['metrics'][m],arms[control]['metrics'][m]
                values[m] = x-y if x is not None and y is not None else None
            comparisons[key] = {'delta_metrics':values}
        return {'arms':arms,'comparisons':comparisons,'queries':len(rows),'visitors':arms['K1']['visitors']}
    floor = max(50,math.ceil(checked/100)); slices = {}
    for f,groups in GROUPS.items():
        slices[f] = {}
        for g in groups:
            value = summarize(scopes[f+'/'+g]); n = value['queries']
            value['support'] = 'empty' if n==0 else 'descriptive_only' if n<floor else 'sufficient_query_count'
            slices[f][g] = value
    uncertainty = check_bootstrap(folder/'bootstrap.jsonl',folder/'reference_bootstrap.jsonl',deltas)
    aggregate = {'main':summarize(scopes['main']),'conditional':summarize(scopes['conditional']),
        'slices':slices,'support_floor_queries':floor,'diagnostics':{k:dict(v) for k,v in diagnostics.items()},
        'fallback_cold_cross_tabs':dict(cross),'roster_sha256':roster.hexdigest(),'uncertainty':uncertainty}
    close(json.loads((folder/'aggregate.json').read_text(encoding='utf-8')),aggregate)
    return {'status':'independent_SQL_full_session_pool_full_catalog_and_Decimal_readback_passed',
            'sessions':len(sessions),'postings':len(support),'memberships':sum(support.values()),
            'queries':checked,'query_nested_scalars_checked':exact_scalars,'bootstrap_replicates':uncertainty['replicates'],
            'production_K1_helpers_imported':False,'sampled_neighbor_or_candidate_oracle':False}
