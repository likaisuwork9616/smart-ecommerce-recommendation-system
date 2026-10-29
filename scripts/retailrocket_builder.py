"""Frozen Retailrocket v1 builder: stdlib CSV/SQLite and streaming causal baskets."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
import csv
from datetime import datetime
import hashlib
import io
from itertools import groupby
import json
from pathlib import Path
import re
import sqlite3
import zipfile

IDENTIFIER = re.compile(r'^(0|[1-9][0-9]*)$', re.ASCII)
HORIZON = 1800000
SCHEMAS = {
    'row_decisions.csv': ['source_record','source_member_sha256','timestamp','visitorid','event','itemid','transactionid','content_sha256','role','canonical_record','decision','reason'],
    'qualified_events.csv': ['source_record','source_member_sha256','timestamp','visitorid','event','itemid','transactionid','content_sha256','role'],
    'duplicate_map.csv': ['source_record','canonical_record','source_member_sha256','content_sha256','role'],
    'exclusions.csv': ['source_record','source_member_sha256','timestamp','visitorid','event','itemid','transactionid','content_sha256','role','canonical_record','decision','reason'],
    'baskets.csv': ['visitorid','session_start_ms','query_ms','role','basket_index','items','source_records','context_item_occurrences'],
    'sessions.csv': ['visitorid','session_start_ms','last_view_ms','basket_count','item_occurrences','first_role','last_role'],
    'query_decisions.csv': ['visitorid','session_start_ms','query_ms','role','basket_index','context_item_occurrences','next_view_ms','next_role','next_in_session','mature','cross_role','status','candidate_count','target_items','target_count','reachable_target_count','all_targets_reachable','visitor_seen_before_fit','targets_seen_before_fit','train_view_events','train_activity_slice'],
    'queries.csv': ['visitorid','session_start_ms','query_ms','role','basket_index','context_item_occurrences','next_view_ms','next_role','next_in_session','mature','cross_role','status','candidate_count','target_items','target_count','reachable_target_count','all_targets_reachable','visitor_seen_before_fit','targets_seen_before_fit','train_view_events','train_activity_slice'],
    'boundary_ledger.csv': ['visitorid','session_start_ms','query_ms','role','next_view_ms','next_role','mature','cross_role','status'],
    'catalog.csv': ['itemid','first_view_ms'],
    'visitor_history.csv': ['visitorid','first_event_ms','train_view_events'],
    'property_versions.csv': ['itemid','property','timestamp','state','value','source_records','category_tree_missing'],
    'view_property_diagnostics.csv': ['visitorid','session_start_ms','query_ms','itemid','available_version_ms','available_state','available_value','available_age_ms','category_version_ms','category_state','category_value','category_age_ms','category_tree_missing'],
    'property_exclusions.csv': ['source_part','source_record','timestamp','itemid','property','value','reason'],
    'category_tree_diagnostics.csv': ['source_record','categoryid','parentid','flags'],
    'orphan_categories.csv': ['categoryid','version_count'],
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def cell(value):
    if value is None:
        return ''
    if isinstance(value, (list, dict)):
        return compact(value)
    if isinstance(value, bool):
        return '1' if value else '0'
    return str(value)


def bounds(policy):
    return [(r,*(int(datetime.fromisoformat(t.replace('Z','+00:00')).timestamp())*1000 for t in policy['time_roles'][r]))
            for r in ('warmup','train','validation','reserved_test')]


def role_for(t, windows):
    for role,start,end in windows:
        if start <= t < end:
            return role
    return 'outside_v1'


def decode_event(raw):
    t,v,e,i,x = raw
    if not all(IDENTIFIER.fullmatch(s) for s in (t,v,i)):
        return 'invalid_timestamp_or_id'
    if e not in ('view','addtocart','transaction'):
        return 'unknown_event'
    if e == 'transaction' and not IDENTIFIER.fullmatch(x):
        return 'transaction_id_missing_or_invalid'
    if e != 'transaction' and x != '':
        return 'nontransaction_has_transaction_id'
    if int(t) > 9223372036854775807:
        return 'timestamp_outside_sqlite_integer_range'
    return ''


def stream_member(z, name, header):
    with z.open(name) as f:
        reader=csv.reader(io.TextIOWrapper(f,encoding='utf-8',newline=''))
        if next(reader,None) != header:
            raise ValueError('Unexpected CSV header: '+name)
        for no,row in enumerate(reader,2):
            if len(row)!=len(header):
                raise ValueError(f'Unexpected CSV record width: {name}:{no}')
            yield no,row


def property_state(prop, values):
    unique=set(values)
    if len(unique)>1:
        return 'conflict',None
    value=next(iter(unique))
    if (prop=='available' and value not in ('0','1')) or (prop=='categoryid' and not IDENTIFIER.fullmatch(value)):
        return 'invalid_value',None
    return 'known',value


def query_decision(t, role, next_t, next_role, windows):
    end=next((end for name,_,end in windows if name==role),None)
    mature=end is not None and t+HORIZON<=end
    same=next_t is not None and 0<next_t-t<=HORIZON
    cross=bool(same and next_role!=role)
    if role=='warmup':
        status='warmup_context_only'
    elif not mature:
        status='right_censored'
    elif not same:
        status='no_observed_continuation'
    elif cross:
        status='cross_role_target'
    else:
        status='labelled'
    return same,mature,cross,status


class Writers:
    def __init__(self, folder):
        self.handles={}
        self.writers={}
        self.counts=Counter()
        for name,header in SCHEMAS.items():
            f=(folder/name).open('x',encoding='utf-8',newline='')
            self.handles[name]=f
            w=csv.writer(f,lineterminator='\n')
            w.writerow(header)
            self.writers[name]=w
    def row(self,name,row):
        if len(row)!=len(SCHEMAS[name]):
            raise ValueError('Output schema width: '+name)
        self.writers[name].writerow([cell(v) for v in row])
        self.counts[name]+=1
    def close(self):
        for f in self.handles.values():
            f.close()


def build(package: Path, policy, audit, folder: Path):
    windows=bounds(policy)
    cutoff={r:s for r,s,e in windows}
    event_sha=next(f['sha256'] for f in audit['files'] if f['name']=='events.csv')
    db=sqlite3.connect(folder/'builder.sqlite')
    db.executescript('''PRAGMA temp_store=MEMORY; PRAGMA journal_mode=OFF;
        CREATE TABLE raw(n INTEGER PRIMARY KEY,rt TEXT,v TEXT,e TEXT,i TEXT,x TEXT,h TEXT,t INTEGER,role TEXT,bad TEXT);
        CREATE TABLE props(part TEXT,n INTEGER,t INTEGER,i TEXT,p TEXT,value TEXT);
        CREATE TABLE versions(i TEXT,p TEXT,t INTEGER,state TEXT,value TEXT,orphan INTEGER,PRIMARY KEY(i,p,t));
    ''')
    out=Writers(folder)
    summary={'scope':{'model_fits':0,'ranking_metrics':0,'reserved_test_scored':False},'roles':{},'source_rows':{},
             'row_decisions':{},'limitations':['anonymous visitor keys','retrospective event-time proxy; no ingestion watermark',
                'no exposures or verified sellable catalog','CC BY-NC-SA 4.0 noncommercial conditions retained']}
    try:
        with zipfile.ZipFile(package) as z:
            if len(z.namelist())!=4 or set(z.namelist())!=set(policy['schemas']):
                raise ValueError('Unexpected ZIP inventory')
            batch=[]
            for no,raw in stream_member(z,'events.csv',policy['schemas']['events.csv']):
                bad=decode_event(raw)
                t=None if bad else int(raw[0])
                role='unknown' if bad else role_for(t,windows)
                batch.append((no,*raw,hashlib.sha256(compact(raw).encode()).hexdigest(),t,role,bad))
                if len(batch)>=20000:
                    db.executemany('INSERT INTO raw VALUES(?,?,?,?,?,?,?,?,?,?)',batch);batch.clear()
            db.executemany('INSERT INTO raw VALUES(?,?,?,?,?,?,?,?,?,?)',batch)
            db.executescript('''CREATE TABLE decisions AS SELECT *,
                CASE WHEN bad='' THEN MIN(n) OVER(PARTITION BY rt,v,e,i,x) END canonical FROM raw;
                CREATE INDEX decisions_view ON decisions(e,v,t);
            ''')
            counts=Counter()
            for n,rt,v,e,i,x,h,t,role,bad,canonical in db.execute('SELECT * FROM decisions ORDER BY n'):
                if bad:
                    decision,reason='excluded',bad
                elif canonical!=n:
                    decision,reason='duplicate','exact_content_duplicate'
                elif role=='outside_v1':
                    decision,reason='excluded','outside_v1_time'
                else:
                    decision,reason='canonical','qualified'
                row=[n,event_sha,rt,v,e,i,x,h,role,canonical,decision,reason]
                out.row('row_decisions.csv',row)
                counts[decision]+=1
                if decision=='duplicate':
                    out.row('duplicate_map.csv',[n,canonical,event_sha,h,role])
                elif decision=='excluded':
                    out.row('exclusions.csv',row)
                else:
                    out.row('qualified_events.csv',row[:9])
            summary['row_decisions']=dict(counts)
            db.executescript("""CREATE TABLE qualified AS SELECT * FROM decisions WHERE bad='' AND n=canonical AND role!='outside_v1';
                CREATE INDEX qualified_clock ON qualified(v,t);
                CREATE TABLE catalog AS SELECT i,MIN(t) first_t FROM qualified WHERE e='view' GROUP BY i;
                CREATE TABLE visitors AS SELECT v,MIN(t) first_t,
                    SUM(CASE WHEN role='train' AND e='view' THEN 1 ELSE 0 END) train_n FROM qualified GROUP BY v;
            """)
            catalog=dict(db.execute('SELECT i,first_t FROM catalog'))
            first_times=sorted(catalog.values())
            visitors={v:(t,n) for v,t,n in db.execute('SELECT v,first_t,train_n FROM visitors')}
            for i,t in db.execute('SELECT i,first_t FROM catalog ORDER BY i'):
                out.row('catalog.csv',[i,t])
            for v,(t,n) in sorted(visitors.items()):
                out.row('visitor_history.csv',[v,t,n])
            print('canonical events and causal first-seen tables written',flush=True)
            tree=list(stream_member(z,'category_tree.csv',policy['schemas']['category_tree.csv']))
            parents={}
            for n,(c,p) in tree:
                parents.setdefault(c,set()).add(p)
            for n,(c,p) in tree:
                flags=[]
                if not IDENTIFIER.fullmatch(c) or (p and not IDENTIFIER.fullmatch(p)):flags.append('invalid_id')
                if len(parents[c])>1:flags.append('conflicting_parent')
                if p and p not in parents:flags.append('missing_parent')
                seen=set();current=c
                while current in parents and len(parents[current])==1:
                    if current in seen:flags.append('cycle');break
                    seen.add(current);current=next(iter(parents[current]))
                    if not current:break
                out.row('category_tree_diagnostics.csv',[n,c,p,sorted(set(flags))])
            for part in ('item_properties_part1.csv','item_properties_part2.csv'):
                nrows=0;batch=[]
                for no,(rt,i,p,value) in stream_member(z,part,policy['schemas'][part]):
                    nrows+=1
                    if not IDENTIFIER.fullmatch(rt) or not IDENTIFIER.fullmatch(i) or not p or not value or int(rt)>9223372036854775807:
                        out.row('property_exclusions.csv',[part,no,rt,i,p,value,'invalid_property_row'])
                    elif p in ('available','categoryid'):
                        batch.append((part,no,int(rt),i,p,value))
                    if len(batch)>=20000:
                        db.executemany('INSERT INTO props VALUES(?,?,?,?,?,?)',batch);batch.clear()
                db.executemany('INSERT INTO props VALUES(?,?,?,?,?,?)',batch)
                summary['source_rows'][part]=nrows
                print(part+' scanned',flush=True)
        db.execute('CREATE INDEX props_key ON props(i,p,t,part,n)')
        batch=[];version_states=Counter();orphans=Counter()
        source=db.execute('SELECT i,p,t,value,part,n FROM props ORDER BY i,p,t,part,n')
        for (i,p,t),group in groupby(source,lambda r:r[:3]):
            records=list(group)
            state,value=property_state(p,[r[3] for r in records])
            orphan=bool(p=='categoryid' and value is not None and value not in parents)
            locators=[[r[4],r[5]] for r in records]
            out.row('property_versions.csv',[i,p,t,state,value,locators,orphan])
            batch.append((i,p,t,state,value,int(orphan)))
            version_states[state]+=1
            if orphan:orphans[value]+=1
            if len(batch)>=20000:
                db.executemany('INSERT INTO versions VALUES(?,?,?,?,?,?)',batch);batch.clear()
        db.executemany('INSERT INTO versions VALUES(?,?,?,?,?,?)',batch)
        db.commit()
        for c,n in sorted(orphans.items()):out.row('orphan_categories.csv',[c,n])
        summary['property_version_states']=dict(version_states)
        summary['orphan_category_ids']=len(orphans)
        roles={r:{'baskets':0,'sessions_starting':0,'statuses':Counter(),'labelled_visitors':set(),'labelled_targets':0,
                  'reachable_targets':0,'all_targets_reachable_queries':0,'new_visitor_queries':0,'new_to_fit_targets':0,
                  'multi_item_context_queries':0,'multi_item_target_queries':0,'min_candidate_count':None,
                  'available_unknown_basket_items':0,'category_unknown_basket_items':0} for r,_,_ in windows}
        def baskets():
            rows=db.execute("SELECT v,t,i,n,role FROM qualified WHERE e='view' ORDER BY v,t,n")
            for (v,t),group in groupby(rows,lambda r:r[:2]):
                records=list(group)
                yield v,t,records[0][4],sorted({r[2] for r in records},key=int),sorted(r[3] for r in records)
        source=iter(baskets());current=next(source,None)
        session_v=None;session_start=None;previous=None;index=0;occurrences=0;first_role=None;last_role=None
        session_count=0
        while current is not None:
            following=next(source,None)
            v,t,role,items,records=current
            new=v!=session_v or t-previous>HORIZON
            if new:
                if session_v is not None:
                    out.row('sessions.csv',[session_v,session_start,previous,index,occurrences,first_role,last_role])
                session_v=v;session_start=t;index=0;occurrences=0;first_role=role
                roles[role]['sessions_starting']+=1;session_count+=1
            index+=1;occurrences+=len(items);last_role=role
            out.row('baskets.csv',[v,session_start,t,role,index,items,records,occurrences])
            next_t=following[1] if following is not None and following[0]==v else None
            next_role=following[2] if next_t is not None else None
            same,mature,cross,status=query_decision(t,role,next_t,next_role,windows)
            targets=following[3] if status=='labelled' else []
            reachable=sum(catalog[i]<t for i in targets)
            fit=cutoff['reserved_test'] if role=='reserved_test' else cutoff['validation']
            first_event,train_n=visitors[v]
            seen=first_event<fit
            known=sum(catalog[i]<fit for i in targets)
            candidate_n=bisect_left(first_times,t)
            activity='0' if train_n==0 else '1' if train_n==1 else '2-5' if train_n<=5 else '6+'
            q=[v,session_start,t,role,index,occurrences,next_t,next_role,same,mature,cross,status,candidate_n,
               targets,len(targets),reachable,(reachable==len(targets)) if targets else None,seen,known,train_n,activity]
            out.row('query_decisions.csv',q)
            r=roles[role];r['baskets']+=1;r['statuses'][status]+=1
            if not mature or cross:
                out.row('boundary_ledger.csv',[v,session_start,t,role,next_t,next_role,mature,cross,status])
            if status=='labelled':
                out.row('queries.csv',q)
                r['labelled_visitors'].add(v);r['labelled_targets']+=len(targets);r['reachable_targets']+=reachable
                r['all_targets_reachable_queries']+=int(reachable==len(targets));r['new_visitor_queries']+=int(not seen)
                r['new_to_fit_targets']+=len(targets)-known
                r['multi_item_context_queries']+=int(len(items)>1);r['multi_item_target_queries']+=int(len(targets)>1)
                r['min_candidate_count']=candidate_n if r['min_candidate_count'] is None else min(candidate_n,r['min_candidate_count'])
            for i in items:
                diagnostics=[];states=[];orphan=False
                for prop in ('available','categoryid'):
                    found=db.execute('SELECT t,state,value,orphan FROM versions WHERE i=? AND p=? AND t<? ORDER BY t DESC LIMIT 1',(i,prop,t)).fetchone()
                    if found is None:
                        diagnostics.extend([None,'no_prior_version',None,None]);states.append('no_prior_version')
                    else:
                        pt,state,value,bad_tree=found
                        diagnostics.extend([pt,state,value,t-pt]);states.append(state)
                        if prop=='categoryid':orphan=bool(bad_tree)
                out.row('view_property_diagnostics.csv',[v,session_start,t,i,*diagnostics,orphan])
                r['available_unknown_basket_items']+=int(states[0]!='known')
                r['category_unknown_basket_items']+=int(states[1]!='known')
            previous=t;current=following
            if sum(out.counts[n] for n in ('baskets.csv',))%500000==0:
                print(f'baskets written: {out.counts["baskets.csv"]}',flush=True)
        if session_v is not None:
            out.row('sessions.csv',[session_v,session_start,previous,index,occurrences,first_role,last_role])
        for role,r in roles.items():
            r['labelled_visitors']=len(r['labelled_visitors']);r['statuses']=dict(r['statuses'])
            n=r['statuses'].get('labelled',0)
            r['support_floor_queries']=max(50,(n+99)//100)
        summary['roles']=roles
        summary['source_rows']['events.csv']=sum(counts.values())
        summary['source_rows']['category_tree.csv']=len(tree)
        summary['sessions']=session_count
        summary['catalog_items']=len(catalog)
        summary['visitors_with_any_qualified_event']=len(visitors)
        summary['files']={name:out.counts[name] for name in SCHEMAS}
        return summary
    finally:
        out.close();db.close()
