"""Train-only adjacent-basket cost ledger; no global D1 or support model."""
from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3

from scripts import retailrocket_popularity_io as old
from scripts import retailrocket_popularity as p

HEADER=['visitorid','session_start_ms','baskets','basket_memberships','distinct_items',
        'adjacent_pairs','raw_directed_emissions','distinct_directed_edges','maximum_adjacent_emissions']


def session_costs(source,header,start,end,watch=lambda:None):
    key=previous=last=None; members=set(); edges=set()
    b=o=adj=raw=maximum=0;iterations=0
    for r in old.records(Path(source),header):
        watch()
        if r['role']!='train':continue
        v=p.item(r['visitorid']);s,t,index=(old.number(r[k]) for k in ('session_start_ms','query_ms','basket_index'))
        if not start<=t<end or s>t or index<1:raise ValueError('Train cost clock/index')
        order=(v,s,t)
        if previous is not None and order<=previous:raise ValueError('Train cost duplicate/order')
        previous=order;current=(v,s)
        if key is not None and current!=key:
            yield (*key,b,o,len(members),adj,raw,len(edges),maximum)
            members=set();edges=set();b=o=adj=raw=maximum=0;last=None
        key=current;ids=set(old.array(r['items']))
        if not ids:raise ValueError('Empty train cost basket')
        b+=1;o+=len(ids);members.update(ids)
        if last is not None and index==last[0]+1 and 0<t-last[1]<=1800000:
            adj+=1;emissions=len(last[2])*len(ids)-len(last[2]&ids)
            raw+=emissions;maximum=max(maximum,emissions)
            for a in last[2]:
                for z in ids:
                    iterations+=1
                    if a!=z:edges.add((a,z))
                    if iterations%50000==0:watch()
        last=(index,t,ids)
    if key is not None:yield (*key,b,o,len(members),adj,raw,len(edges),maximum)


def summarize(rows):
    result={k:0 for k in ('train_sessions','train_baskets','basket_item_memberships','distinct_session_item_memberships',
        'eligible_adjacent_pairs','raw_directed_emissions','session_unique_directed_emissions',
        'singleton_sessions','zero_directed_edge_sessions','maximum_session_items','maximum_session_baskets',
        'maximum_session_raw_emissions','maximum_session_distinct_directed_edges','maximum_adjacent_emissions')}
    hist=Counter()
    for _,_,b,o,n,adj,raw,u,m in rows:
        result['train_sessions']+=1;result['train_baskets']+=b;result['basket_item_memberships']+=o
        result['distinct_session_item_memberships']+=n;result['eligible_adjacent_pairs']+=adj
        result['raw_directed_emissions']+=raw;result['session_unique_directed_emissions']+=u
        result['singleton_sessions']+=n==1;result['zero_directed_edge_sessions']+=u==0
        for k,value in [('maximum_session_items',n),('maximum_session_baskets',b),('maximum_session_raw_emissions',raw),
                         ('maximum_session_distinct_directed_edges',u),('maximum_adjacent_emissions',m)]:result[k]=max(result[k],value)
        hist[u]+=1
    result['repeated_directed_emissions']=result['raw_directed_emissions']-result['session_unique_directed_emissions']
    result['session_unique_edge_histogram']={str(k):hist[k] for k in sorted(hist)}
    return result


def audit(source,header,start,end,folder,watch=lambda:None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    ledger=folder/'train_session_costs.csv'
    with ledger.open('x',encoding='utf-8',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(HEADER)
        def rows():
            for row in session_costs(source,header,start,end,watch):w.writerow(row);yield row
        result=summarize(rows())
    db=sqlite3.connect(folder/'independent_cost.sqlite')
    # SQLite raw train inputs and per-session scalar costs only, never a D_ij table.
    db.execute('PRAGMA temp_store=MEMORY');db.set_progress_handler(lambda:(watch() or 0),50000)
    try:
        db.execute('CREATE TABLE b(v TEXT,s INTEGER,k INTEGER,t INTEGER,n INTEGER,PRIMARY KEY(v,s,k))')
        db.execute('CREATE TABLE m(v TEXT,s INTEGER,k INTEGER,i TEXT,PRIMARY KEY(v,s,k,i))')
        with Path(source).open(encoding='utf-8',newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=header:raise ValueError('Cost oracle schema')
            for r in reader:
                watch()
                if None in r or any(x is None for x in r.values()):raise ValueError('Cost oracle CSV width')
                if r['role']!='train':continue
                v=r['visitorid'];s,t,k=(int(r[z]) for z in ('session_start_ms','query_ms','basket_index'))
                if str(int(v))!=v or int(v)<0 or not start<=t<end or s>t or k<1:raise ValueError('Cost oracle key/time')
                ids=json.loads(r['items'])
                if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids):raise ValueError('Cost oracle items')
                if any(type(i) is not str or str(int(i))!=i or int(i)<0 for i in ids):raise ValueError('Cost oracle item ID')
                db.execute('INSERT INTO b VALUES(?,?,?,?,?)',(v,s,k,t,len(ids)))
                db.executemany('INSERT INTO m VALUES(?,?,?,?)',[(v,s,k,i) for i in ids])
        db.execute('CREATE TABLE cards AS SELECT v,s,COUNT(DISTINCT i) n FROM m GROUP BY v,s')
        db.execute('''CREATE TABLE adjacency_cost AS SELECT a.v,a.s,a.k,
          a.n*z.n-(SELECT COUNT(*) FROM m x JOIN m y ON x.i=y.i
                    WHERE x.v=a.v AND x.s=a.s AND x.k=a.k AND y.v=z.v AND y.s=z.s AND y.k=z.k) raw
          FROM b a JOIN b z ON a.v=z.v AND a.s=z.s AND z.k=a.k+1 AND z.t>a.t AND z.t-a.t<=1800000''')
        db.execute('''CREATE TABLE session_edges_cost AS SELECT a.v,a.s,COUNT(*) raw,
          COUNT(DISTINCT x.i||','||y.i) u FROM b a JOIN b z
          ON a.v=z.v AND a.s=z.s AND z.k=a.k+1 AND z.t>a.t AND z.t-a.t<=1800000
          JOIN m x ON x.v=a.v AND x.s=a.s AND x.k=a.k
          JOIN m y ON y.v=z.v AND y.s=z.s AND y.k=z.k AND x.i!=y.i GROUP BY a.v,a.s''')
        db.execute('CREATE TABLE ac AS SELECT v,s,COUNT(*) n,SUM(raw) raw,MAX(raw) mx FROM adjacency_cost GROUP BY v,s')
        db.execute('CREATE UNIQUE INDEX ac_key ON ac(v,s)');db.execute('CREATE UNIQUE INDEX ec_key ON session_edges_cost(v,s)')
        cursor=db.execute('''SELECT b.v,b.s,COUNT(*),SUM(b.n),c.n,COALESCE(ac.n,0),COALESCE(ac.raw,0),
          COALESCE(ec.u,0),COALESCE(ac.mx,0) FROM b JOIN cards c ON b.v=c.v AND b.s=c.s
          LEFT JOIN ac ON b.v=ac.v AND b.s=ac.s LEFT JOIN session_edges_cost ec ON b.v=ec.v AND b.s=ec.s
          GROUP BY b.v,b.s ORDER BY b.v,b.s''')
        checked=0
        with ledger.open(encoding='utf-8',newline='') as f:
            reader=csv.DictReader(f)
            def verified_rows():
                nonlocal checked
                for actual in cursor:
                    watch();r=next(reader,None)
                    expected=None if r is None else (r[HEADER[0]],*(int(r[k]) for k in HEADER[1:]))
                    if expected!=actual:raise ValueError('Independent train session cost row differs')
                    checked+=1;yield actual
            independent=summarize(verified_rows())
            if next(reader,None) is not None or independent!=result:raise ValueError('Independent cost aggregate/length')
        scalar=db.execute('SELECT COALESCE(SUM(raw),0) FROM session_edges_cost').fetchone()[0]
        if scalar!=result['raw_directed_emissions']:raise ValueError('Independent raw Cartesian emissions differ')
        result.update(independent_rows_checked=checked,independent_cells_checked=checked*len(HEADER),independent_cost_passes=2,
          global_directed_count_model_built=False,item_support_model_built=False,validation_or_test_items_decoded=False,
          work_unit='raw adjacent directed emissions and per-session distinct edges; no global item-pair aggregation')
        db.commit();watch()
        with (folder/'cost.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
        return result
    finally:db.close()
