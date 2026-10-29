"""Independent SQL reconstruction, full-order rational and bootstrap readback.

Does not import the new production core, adapter, or bootstrap implementation.
Reuses the already frozen independent Decimal metric oracle only.
"""
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import groupby
import csv
import hashlib
import json
import math
import sqlite3
import struct
import numpy as np

from scripts.retailrocket_popularity_oracle import Fold, close, terms, read_rows, num, ms, GROUPS, METRICS, FIELDS


def encoded(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def jsonlines(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream: yield json.loads(line)


def check_bootstrap(path,records,watch=lambda:None):
    grouped=defaultdict(list)
    for v,d in records: grouped[v].append(d)
    if not grouped:
        if next(jsonlines(path),None) is not None: raise ValueError('Extra bootstrap records')
        return {'replicates':0,'visitors':0,'mean_delta':None,'interval':None,'reason':'zero_queries'}
    visitors=sorted(grouped,key=int);n=[len(grouped[v]) for v in visitors];d=[math.fsum(grouped[v]) for v in visitors]
    generator=np.random.Generator(np.random.PCG64(42));output=iter(jsonlines(path));deltas=[]
    for b in range(2000):
        watch();before=generator.bit_generator.state
        drawn=generator.integers(0,len(visitors),size=len(visitors),dtype=np.int64).tolist()
        multiplicity=Counter(drawn)
        denominator=sum(n[index] for index in drawn)
        delta=math.fsum(multiplicity.get(i,0)*d[i] for i in range(len(visitors)))/denominator
        drawhash=hashlib.sha256(struct.pack('<'+'q'*len(drawn),*drawn)).hexdigest()
        expected={'replicate':b,'draw_sha256':drawhash,'query_denominator':denominator,'delta':delta,
                  'rng_before':before,'rng_after':generator.bit_generator.state}
        actual=next(output,None)
        if actual is None: raise ValueError('Missing bootstrap record')
        close(actual,expected,'bootstrap')
        deltas.append(delta)
    if next(output,None) is not None: raise ValueError('Extra bootstrap record')
    sorted_values=sorted(deltas)
    interval=[]
    for probability in (.025,.975):
        position=(len(deltas)-1)*probability;lower=math.floor(position);fraction=position-lower
        interval.append(sorted_values[lower]+fraction*(sorted_values[min(lower+1,len(deltas)-1)]-sorted_values[lower]))
    return {'replicates':2000,'visitors':len(visitors),'mean_delta':math.fsum(x[1] for x in records)/len(records),
            'interval':interval,'reason':None}


class PairOracle:
    def __init__(self,catalog):
        self.folds={a:Fold(catalog) for a in ('P0','C1')};self.diff={m:[] for m in METRICS}
    def add(self,q,ids,values,reachable,delta):
        for a in self.folds: self.folds[a].add(q,ids[a],values[a],reachable)
        for m in self.diff: self.diff[m].append(delta[m])
    def result(self):
        arms={a:f.result() for a,f in self.folds.items()};n=arms['P0']['queries']
        delta={m:math.fsum(v)/n if n else None for m,v in self.diff.items()}
        for m in ('visitor_macro_ndcg','catalog_coverage'):
            a,b=arms['C1']['metrics'][m],arms['P0']['metrics'][m];delta[m]=a-b if a is not None and b is not None else None
        return arms,{'queries':n,'visitors':arms['P0']['visitors'],'delta_metrics':delta}


def verify(folder,source,baseline,schemas,policy,parent,brute=False,watch=lambda:None):
    dbpath=folder/'oracle.sqlite'
    if dbpath.exists(): raise FileExistsError('Independent oracle database already exists; no replay')
    db=sqlite3.connect(dbpath);db.execute('PRAGMA temp_store=MEMORY')
    rows_checked=Counter();cells_checked=Counter()
    start,end=map(ms,(policy['comparison']['fit_start_inclusive_utc'],policy['comparison']['fit_end_exclusive_utc']))
    try:
        db.execute('CREATE TABLE history(v TEXT,s INTEGER,t INTEGER,idx INTEGER,items TEXT,role TEXT,n INTEGER,PRIMARY KEY(v,s,t))')
        db.execute('CREATE TABLE membership(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        for r in read_rows(source/'baskets.csv',schemas['baskets.csv']):
            watch()
            if r['role'] not in ('warmup','train','validation'): continue
            v=r['visitorid'];num(v);s=num(r['session_start_ms']);t=num(r['query_ms']);index=num(r['basket_index'])
            items=json.loads(r['items'])
            if not items or len(items)!=len(set(items)): raise ValueError('Oracle invalid basket')
            for i in items:num(i)
            db.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?)',(v,s,t,index,r['items'],r['role'],len(items)))
            if r['role']=='train':
                if not start<=t<end: raise ValueError('Oracle fit clock')
                db.executemany('INSERT OR IGNORE INTO membership VALUES(?,?,?)',[(v,s,i) for i in items])
        db.execute('CREATE TABLE support AS SELECT i,COUNT(*) AS n FROM membership GROUP BY i')
        db.execute('CREATE TABLE edges AS SELECT a.i AS a,b.i AS b,COUNT(*) AS n FROM membership a JOIN membership b ON a.v=b.v AND a.s=b.s WHERE CAST(a.i AS INTEGER)<CAST(b.i AS INTEGER) GROUP BY a.i,b.i')
        db.execute('CREATE UNIQUE INDEX edges_ab ON edges(a,b)');db.execute('CREATE INDEX edges_b ON edges(b)')
        db.execute("CREATE TABLE trainmeta AS SELECT v,s,COUNT(*) AS b,SUM(n) AS o FROM history WHERE role='train' GROUP BY v,s")
        db.execute('CREATE UNIQUE INDEX trainmeta_key ON trainmeta(v,s)')
        support=dict(db.execute('SELECT i,n FROM support'));counts={r['itemid']:num(r['count']) for r in read_rows(baseline/'item_counts.csv',FIELDS['item_counts.csv'])}
        if set(support)!=set(counts) or any(support[i]>counts[i] for i in support): raise ValueError('Oracle support identity')
        digest=hashlib.sha256(f'C1_binary_session_conditional_sum_v1\n{start},{end}\n'.encode())
        actual_support=iter(read_rows(folder/'support.csv',['itemid','support']))
        for i,n in sorted(support.items(),key=lambda x:int(x[0])):
            actual=next(actual_support,None)
            if actual!={'itemid':i,'support':str(n)}: raise ValueError('Oracle support cell mismatch')
            digest.update(f'S,{i},{n}\n'.encode());rows_checked['support.csv']+=1;cells_checked['support.csv']+=2
        if next(actual_support,None) is not None: raise ValueError('Extra support row')
        actual_pairs=iter(read_rows(folder/'pairs.csv',['itemid_a','itemid_b','count']));pair_sum=0
        for a,b,n in db.execute('SELECT a,b,n FROM edges ORDER BY CAST(a AS INTEGER),CAST(b AS INTEGER)'):
            watch();actual=next(actual_pairs,None)
            if actual!={'itemid_a':a,'itemid_b':b,'count':str(n)} or not 0<n<=min(support[a],support[b]): raise ValueError('Oracle pair cell mismatch')
            digest.update(f'C,{a},{b},{n}\n'.encode());pair_sum+=n;rows_checked['pairs.csv']+=1;cells_checked['pairs.csv']+=3
        if next(actual_pairs,None) is not None: raise ValueError('Extra pair row')
        fit_id=digest.hexdigest();actual_sessions=iter(jsonlines(folder/'train_sessions.jsonl'));sessions=singletons=basket_n=occurrences=emissions=0
        cursor=db.execute('SELECT m.v,m.s,m.i,t.b,t.o FROM membership m JOIN trainmeta t ON m.v=t.v AND m.s=t.s ORDER BY m.v,m.s,CAST(m.i AS INTEGER)')
        for key,values in groupby(cursor,key=lambda x:x[:2]):
            watch();values=list(values);ids=[v[2] for v in values];b,o=values[0][3:];n=len(ids)
            expected={'key':list(key),'items':ids,'baskets':b,'basket_memberships':o}
            if next(actual_sessions,None)!=expected: raise ValueError('Oracle session lineage differs')
            sessions+=1;singletons+=n==1;basket_n+=b;occurrences+=o;emissions+=n*(n-1)//2
            rows_checked['train_sessions.jsonl']+=1;cells_checked['train_sessions.jsonl']+=4
        if next(actual_sessions,None) is not None or pair_sum!=emissions: raise ValueError('Oracle session/pair accounting')
        audit={'train_sessions':sessions,'singleton_sessions':singletons,'train_baskets':basket_n,'basket_item_memberships':occurrences,
               'distinct_session_item_memberships':sum(support.values()),'exact_unordered_pair_emissions':emissions,
               'unique_pairs':rows_checked['pairs.csv'],'positive_support_items':len(support),'start_ms':start,'end_ms':end,'fit_id':fit_id}
        close(json.loads((folder/'fit_audit.json').read_text()),audit)
        catalog={r['itemid']:num(r['first_view_ms']) for r in read_rows(source/'catalog.csv',schemas['catalog.csv'])}
        first_times=sorted(catalog.values())
        fallback=sorted(catalog,key=lambda i:(-counts.get(i,0),int(i)))
        main=PairOracle(catalog);conditional=PairOracle(catalog);groups={f:{g:PairOracle(catalog) for g in names} for f,names in GROUPS.items()}
        outputs=iter(jsonlines(folder/'queries.jsonl'));rankrows=iter(read_rows(baseline/'ranked_queries.csv',FIELDS['ranked_queries.csv']))
        metricrows=iter(read_rows(baseline/'query_metrics.csv',FIELDS['query_metrics.csv']));slicerows=iter(read_rows(baseline/'query_slices.csv',FIELDS['query_slices.csv']))
        records=[];roster=hashlib.sha256();diagnostics={k:Counter() for k in ('history_size','supported_seeds','positive_evidence','fallback_reason','zero_fill_slots')}
        previous=None
        for r in read_rows(source/'queries.csv',schemas['queries.csv']):
            if r['role']!='validation': continue
            watch();v=r['visitorid'];s=num(r['session_start_ms']);t=num(r['query_ms']);index=num(r['basket_index']);key=(v,s,t)
            if previous is not None and key<=previous: raise ValueError('Oracle query order')
            previous=key;current=db.execute('SELECT idx,n FROM history WHERE v=? AND s=? AND t=?',key).fetchone()
            if current is None or current[0]!=index: raise ValueError('Oracle missing current')
            history=set()
            for row in db.execute('SELECT items FROM history WHERE v=? AND s=? AND t<=? AND idx<=? ORDER BY t',(v,s,t,index)):
                history.update(json.loads(row[0]))
            history=sorted(history,key=int)
            if not history: raise ValueError('Oracle empty history')
            score=defaultdict(Fraction);supported=sum(i in support for i in history)
            for i in history:
                if i not in support: continue
                for j,n in db.execute('SELECT b,n FROM edges WHERE a=? UNION ALL SELECT a,n FROM edges WHERE b=?',(i,i)):
                    if catalog[j]<t: score[j]+=Fraction(n,support[i])
            eligible=[i for i in catalog if catalog[i]<t] if brute else None
            if brute:
                ids=sorted(eligible,key=lambda j:(-score.get(j,Fraction()),-counts.get(j,0),int(j)))[:10]
            else:
                # Every item outside the complete SQL neighbor union has exactly
                # zero score. This partitions the full catalog without top-L.
                ids=sorted(score,key=lambda j:(-score[j],-counts.get(j,0),int(j)))[:10]
                for j in fallback:
                    if len(ids)>=10: break
                    if j not in ids and catalog[j]<t: ids.append(j)
            candidate=sum(first<t for first in catalog.values()) if brute else __import__('bisect').bisect_left(first_times,t)
            ids=ids[:min(10,candidate)]
            evidence=len(score);fallback_reason=None if score else 'no_supported_seeds' if not supported else 'no_positive_causal_neighbor'
            fractions=[score.get(i,Fraction()) for i in ids]
            prediction={'fit_id':fit_id,'ids':ids,'scores':[[x.numerator,x.denominator] for x in fractions],
                        'p0_counts':[counts.get(i,0) for i in ids],'candidate_count':candidate,'supported_seeds':supported,
                        'positive_candidates':evidence,'zero_fill_slots':sum(x==0 for x in fractions),'fallback_reason':fallback_reason}
            targets=json.loads(r['target_items']);reachable=sum(i in catalog and catalog[i]<t for i in targets)
            if candidate!=num(r['candidate_count']) or reachable!=num(r['reachable_target_count']): raise ValueError('Oracle denominator differs')
            pr=next(rankrows,None);pm=next(metricrows,None);ps=next(slicerows,None);actual=next(outputs,None)
            if any(x is None for x in (pr,pm,ps,actual)): raise ValueError('Oracle missing paired row')
            for x in (pr,pm,ps):
                if (x['visitorid'],num(x['session_start_ms']),num(x['query_ms']))!=key or x['role']!='validation': raise ValueError('Oracle pair key')
            p0ids=json.loads(pr['top10_items']);t0,exact0=terms(p0ids,targets);t1,exact1=terms(ids,targets)
            expected0={k:float(pm[k]) for k in ('dcg','idcg',*METRICS)}
            expected0.update(target_count=num(pm['target_count']),hits=num(pm['hits']),first_hit_rank=num(pm['first_hit_rank']) if pm['first_hit_rank'] else None)
            close(expected0,t0)
            if actual['predictions']['C1']!=prediction: raise ValueError('Oracle exact C1 rational/order/evidence differs')
            close(actual['terms']['C1'],t1);close(actual['terms']['P0'],expected0)
            current_n=current[1];train=num(r['train_view_events']);known=sum(i in support for i in targets)
            memberships={'visitor_history':'seen' if r['visitor_seen_before_fit']=='1' else 'new',
                'current_basket':'multiple' if current_n>1 else 'single','target_basket':'multiple' if len(targets)>1 else 'single',
                'train_activity':'0' if not train else '1' if train==1 else '2-5' if train<=5 else '6+',
                'target_model':'all_positive' if known==len(targets) else 'all_zero' if not known else 'mixed'}
            if any(ps[k]!=g for k,g in memberships.items()): raise ValueError('Oracle inherited slice')
            delta={m:actual['terms']['C1'][m]-expected0[m] for m in METRICS}
            expected={'key':list(key),'history':history,'history_sha256':hashlib.sha256(encoded(history).encode()).hexdigest(),
                'targets':targets,'candidate_count':candidate,'reachable_targets':reachable,
                'predictions':{'P0':{'ids':p0ids,'candidate_count':num(pr['candidate_count'])},'C1':prediction},
                'terms':{'P0':expected0,'C1':t1},'delta':delta,'slices':memberships}
            close(actual,expected)
            oq={'v':v,'t':t,'targets':targets};values={'P0':exact0,'C1':exact1};allids={'P0':p0ids,'C1':ids}
            main.add(oq,allids,values,reachable,delta)
            if reachable==len(targets): conditional.add(oq,allids,values,reachable,delta)
            for family,g in memberships.items(): groups[family][g].add(oq,allids,values,reachable,delta)
            diagnostics['history_size'][str(len(history))]+=1;diagnostics['supported_seeds'][str(supported)]+=1
            diagnostics['positive_evidence']['0' if not evidence else '1-9' if evidence<10 else 'at_least_10']+=1
            diagnostics['fallback_reason'][fallback_reason or 'positive_evidence']+=1;diagnostics['zero_fill_slots'][str(prediction['zero_fill_slots'])]+=1
            records.append((v,delta['ndcg']));roster.update((encoded(list(key))+'\n').encode());rows_checked['queries.jsonl']+=1;cells_checked['queries.jsonl']+=10
        if any(next(iterator,None) is not None for iterator in (outputs,rankrows,metricrows,slicerows)): raise ValueError('Oracle extra paired query')
        arms,paired=main.result();ca,paired['conditional']=conditional.result();floor=max(50,(paired['queries']+99)//100);paired['slices']={}
        for a in arms:arms[a].update(conditional=ca[a],support_floor_queries=floor,slices={})
        for family,buckets in groups.items():
            paired['slices'][family]={}
            for a in arms:arms[a]['slices'][family]={}
            for g,fold in buckets.items():
                ga,gp=fold.result();n=gp['queries'];flag='empty' if not n else 'descriptive_only' if n<floor else 'sufficient_query_count'
                gp['support']=flag;paired['slices'][family][g]=gp
                for a in arms:ga[a]['support']=flag;arms[a]['slices'][family][g]=ga[a]
        uncertainty=check_bootstrap(folder/'bootstrap.jsonl',records,watch)
        rows_checked['bootstrap.jsonl']=uncertainty['replicates'];cells_checked['bootstrap.jsonl']=uncertainty['replicates']*6
        result={'arms':arms,'paired':paired,'diagnostics':{k:dict(v) for k,v in diagnostics.items()},'uncertainty':uncertainty,'roster_sha256':roster.hexdigest()}
        close(json.loads((folder/'aggregate.json').read_text()),result)
        db.commit()
        return {'aggregate':result,'rows':dict(rows_checked),'top_level_cells':dict(cells_checked),
                'all_nested_JSON_values_checked':True,'ranking_oracle':'full causal catalog sort' if brute else 'all SQL neighbors plus exact zero-score complement proof',
                'fit_audit':audit}
    finally:
        db.close()
